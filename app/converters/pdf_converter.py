"""
Conversores de PDF.

Duas direções, cada uma em sua classe, porque são operações bem
diferentes por dentro:

- `ImageToPdfConverter` — uma imagem vira um PDF de uma página (Pillow).
- `PdfToImageConverter` — um PDF vira imagens, uma por página (PyMuPDF
  para renderizar, Pillow para gravar com as mesmas regras de qualidade
  usadas no conversor de imagens).

Como nas imagens, a interface não sabe qual biblioteca está por trás:
ela só pede "converta este arquivo para .pdf" e recebe de volta um
`ConversionResult`.

Sobre PDFs com várias páginas: um PDF de página única vira exatamente
o arquivo pedido. Um PDF com várias páginas viraria dezenas de
arquivos soltos na pasta de saída, então as páginas vão para uma
subpasta com o nome do documento (`relatorio/relatorio_p01.png`, ...).
Se já existir uma pasta com esse nome, uma nova é criada com sufixo
numérico, para nunca sobrescrever um resultado anterior.

Sobre páginas enormes: a rasterização normal é a 150 dpi, mas uma
página fora do comum (banner, planta de engenharia, PDF malformado que
declara uma página de metros) geraria uma imagem de centenas de milhões
de pixels. Nesses casos a resolução é reduzida até a imagem caber num
teto de memória e no maior lado que o formato de destino aceita gravar
(ver `render_zoom`).
"""

from __future__ import annotations

import math
import time
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

from app.converters.image_converter import (
    FORMATS_WITHOUT_ALPHA,
    PILLOW_FORMAT,
    SOURCE_FORMATS,
    TARGET_FORMATS,
    flatten_onto_background,
    frame_count,
    has_alpha,
    is_multipage_tiff,
    save_options,
)
from app.core.converter import BaseConverter, ConversionResult, refuse_overwriting_source
from app.core.task_context import NULL_CONTEXT, OperationCancelled, TaskContext
from app.utils.file_utils import (
    discard_partial_outputs,
    ensure_directory,
    get_extension,
    get_filename,
    page_destinations,
    temp_output_path,
)
from app.utils.logger import get_logger

# O PyMuPDF é opcional de propósito: sem ele, "imagens -> PDF" (que só
# precisa de Pillow) continua funcionando, e apenas "PDF -> imagens"
# deixa de ser registrado na camada de compatibilidade.
try:  # PyMuPDF >= 1.24 expõe o nome novo; versões antigas, só o antigo.
    import pymupdf
except ImportError:  # pragma: no cover — depende da versão instalada
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None  # type: ignore[assignment]

PYMUPDF_AVAILABLE = pymupdf is not None

logger = get_logger("converters.pdf")

# Imagens que sabemos transformar em página de PDF, e formatos de imagem
# que sabemos gerar a partir de um PDF: os mesmos do conversor de imagens.
IMAGE_SOURCE_FORMATS: set[str] = set(SOURCE_FORMATS)
IMAGE_TARGET_FORMATS: set[str] = set(TARGET_FORMATS)

# Resolução usada para rasterizar uma página de PDF. 150 dpi é o meio
# termo entre legibilidade (dá para ler texto pequeno) e tamanho de
# arquivo — 300 dpi quadruplica os bytes sem ganho perceptível na tela.
PDF_RENDER_DPI = 150

# Teto de pixels de uma página rasterizada. Uma página A0 a 150 dpi dá
# uns 35 milhões de pixels e ainda passa inteira; acima de 50 milhões a
# memória vira o problema — a imagem existe duas vezes durante a
# gravação (a do PyMuPDF e a cópia do Pillow), a 3 bytes por pixel.
MAX_RENDER_PIXELS = 50_000_000

# Maior lado, em pixels, que cada formato consegue gravar. O WEBP tem um
# limite duro de 16383 px, e acima dele o Pillow recusa a gravação — o
# que chegava ao usuário como "erro inesperado" numa página comprida. O
# JPEG vai até 65500 px; o PNG não tem limite que importe aqui.
_MAX_SIDE_BY_FORMAT: dict[str, int] = {"webp": 16383, "jpg": 65500, "jpeg": 65500}

# Resolução assumida ao criar um PDF a partir de uma imagem que não
# declara DPI. 72 dpi faz a página do PDF ter exatamente o tamanho da
# imagem em pontos, sem redimensionar nada.
DEFAULT_IMAGE_RESOLUTION = 72.0

# Limites de sanidade para o DPI declarado dentro do arquivo: valores
# fora disso costumam ser metadado errado e gerariam páginas absurdas.
_MIN_RESOLUTION = 36.0
_MAX_RESOLUTION = 1200.0

# Modos que o Pillow consegue gravar direto em uma página de PDF.
_PDF_PAGE_MODES = {"1", "L", "RGB", "CMYK"}


def _failure(input_path: str, message: str) -> ConversionResult:
    logger.warning("Conversão falhou | %s | %s", get_filename(input_path), message)
    return ConversionResult(success=False, input_path=input_path, error_message=message)


def _resolution_for(image: Image.Image) -> float:
    """DPI a usar na página do PDF, respeitando o que a imagem declara
    quando o valor é plausível."""
    dpi = image.info.get("dpi")
    if isinstance(dpi, (tuple, list)) and dpi:
        try:
            value = float(dpi[0])
        except (TypeError, ValueError):
            return DEFAULT_IMAGE_RESOLUTION
        if _MIN_RESOLUTION <= value <= _MAX_RESOLUTION:
            return value
    return DEFAULT_IMAGE_RESOLUTION


def render_zoom(page_width: float, page_height: float, target_ext: str) -> float:
    """Fator de ampliação (pontos -> pixels) para rasterizar uma página.

    O normal é `PDF_RENDER_DPI / 72`. Só uma página fora do comum sai
    com menos: o fator é reduzido até a imagem caber em
    `MAX_RENDER_PIXELS` e no maior lado que o formato de destino aceita.
    A página continua inteira — perde resolução, não conteúdo.

    O limite de lado mira um pixel abaixo do máximo porque o PyMuPDF
    arredonda o tamanho da imagem para cima: mirar no próprio máximo
    deixaria a imagem, às vezes, um pixel acima dele.
    """
    zoom = PDF_RENDER_DPI / 72
    width = max(page_width, 1.0)
    height = max(page_height, 1.0)

    pixels = width * height * zoom * zoom
    if pixels > MAX_RENDER_PIXELS:
        zoom *= math.sqrt(MAX_RENDER_PIXELS / pixels)

    max_side = _MAX_SIDE_BY_FORMAT.get(target_ext)
    if max_side is not None:
        longest = max(width, height) * zoom
        if longest > max_side - 1:
            zoom *= (max_side - 1) / longest

    return zoom


def _prepare_page(image: Image.Image) -> Image.Image:
    """Deixa a imagem no formato que uma página de PDF aceita: sem canal
    alfa (o PDF não guarda transparência de página) e em um modo de cor
    que o Pillow saiba gravar."""
    image = ImageOps.exif_transpose(image) or image
    if has_alpha(image):
        return flatten_onto_background(image)
    if image.mode in _PDF_PAGE_MODES:
        return image
    return image.convert("RGB")


class ImageToPdfConverter(BaseConverter):
    """Transforma uma imagem em um PDF (Pillow).

    A página fica do tamanho exato da imagem, sem recorte nem
    redimensionamento: se a imagem declara DPI, ele é respeitado; caso
    contrário, assume-se 72 dpi.

    Um TIFF de várias páginas vira um PDF com todas elas, gravadas uma de
    cada vez — uma digitalização colorida de dezenas de páginas não cabe
    inteira na memória. Um GIF animado entra só com o primeiro quadro.
    """

    @property
    def source_formats(self) -> set[str]:
        return set(IMAGE_SOURCE_FORMATS)

    @property
    def target_formats(self) -> set[str]:
        return {"pdf"}

    def convert(
        self, input_path: str, output_path: str, context: TaskContext | None = None
    ) -> ConversionResult:
        context = context or NULL_CONTEXT
        source = Path(input_path)
        destination = Path(output_path)
        started_at = time.monotonic()

        if get_extension(destination) != "pdf":
            return _failure(
                input_path, "Este conversor só sabe gravar PDF a partir de imagens."
            )
        if not source.is_file():
            return _failure(
                input_path, f"O arquivo '{get_filename(source)}' não foi encontrado."
            )
        refused = refuse_overwriting_source(input_path, output_path)
        if refused is not None:
            return refused

        temp_output: Path | None = None
        try:
            context.check_cancelled()
            ensure_directory(destination.parent)
            temp_output = temp_output_path(destination)

            with Image.open(source) as image:
                if is_multipage_tiff(image):
                    total = frame_count(image)
                    for index, frame in enumerate(ImageSequence.Iterator(image)):
                        context.check_cancelled()
                        _prepare_page(frame).save(
                            temp_output,
                            format="PDF",
                            resolution=_resolution_for(frame),
                            append=index > 0,
                        )
                        context.report_step(index + 1, total)
                else:
                    page = _prepare_page(image)
                    page.save(temp_output, format="PDF", resolution=_resolution_for(image))

            temp_output.replace(destination)
            temp_output = None
        except OperationCancelled:
            raise  # não é falha: quem trata é a fila
        except UnidentifiedImageError:
            return _failure(
                input_path,
                f"'{get_filename(source)}' não é uma imagem válida ou está corrompido.",
            )
        except PermissionError:
            return _failure(
                input_path,
                "Sem permissão para gravar na pasta de destino. "
                "Escolha outra pasta nas configurações.",
            )
        except OSError as exc:
            logger.exception("Erro de sistema ao gerar PDF de %s", input_path)
            detail = getattr(exc, "strerror", None) or str(exc)
            return _failure(input_path, f"Não foi possível gravar o PDF ({detail}).")
        except Exception:  # noqa: BLE001 — a UI nunca deve receber um traceback
            logger.exception("Falha inesperada ao gerar PDF de %s", input_path)
            return _failure(
                input_path, "Erro inesperado ao gerar o PDF. Veja os logs para detalhes."
            )
        finally:
            if temp_output is not None:
                temp_output.unlink(missing_ok=True)

        context.report(100)
        logger.info(
            "Conversão concluída | Pillow | %s -> %s | %.2fs",
            get_filename(source),
            get_filename(destination),
            time.monotonic() - started_at,
        )
        return ConversionResult(
            success=True, input_path=input_path, output_path=str(destination)
        )


class PdfToImageConverter(BaseConverter):
    """Rasteriza as páginas de um PDF em imagens (PyMuPDF + Pillow)."""

    @property
    def source_formats(self) -> set[str]:
        return {"pdf"}

    @property
    def target_formats(self) -> set[str]:
        return set(IMAGE_TARGET_FORMATS)

    def convert(
        self, input_path: str, output_path: str, context: TaskContext | None = None
    ) -> ConversionResult:
        context = context or NULL_CONTEXT
        source = Path(input_path)
        destination = Path(output_path)
        target_ext = get_extension(destination)
        started_at = time.monotonic()

        if not PYMUPDF_AVAILABLE:  # rede de segurança: sem PyMuPDF nem é registrado
            return _failure(
                input_path,
                "A leitura de PDF depende do PyMuPDF, que não está instalado. "
                "Rode 'pip install -r requirements.txt' para habilitá-la.",
            )
        if target_ext not in PILLOW_FORMAT:
            return _failure(
                input_path,
                f"O FileMorph ainda não sabe gravar páginas de PDF em .{target_ext}.",
            )
        if not source.is_file():
            return _failure(
                input_path, f"O arquivo '{get_filename(source)}' não foi encontrado."
            )
        refused = refuse_overwriting_source(input_path, output_path)
        if refused is not None:
            return refused

        document = None
        written: list[Path] = []
        # A subpasta nova de um PDF de várias páginas. Guardada à parte, e
        # não deduzida de `written`, porque uma falha antes da primeira
        # página precisa removê-la mesmo sem nenhum arquivo gravado.
        created_folder: Path | None = None
        try:
            try:
                document = pymupdf.open(source)
            except Exception:  # noqa: BLE001 — PyMuPDF sinaliza arquivo ruim assim
                logger.exception("PDF ilegível: %s", input_path)
                return _failure(
                    input_path,
                    f"'{get_filename(source)}' não é um PDF válido ou está corrompido.",
                )

            if document.needs_pass:
                return _failure(
                    input_path,
                    f"'{get_filename(source)}' está protegido por senha. "
                    "Remova a proteção antes de converter.",
                )

            page_count = document.page_count
            if page_count == 0:
                return _failure(input_path, f"'{get_filename(source)}' não tem páginas.")

            created_folder, targets = page_destinations(destination, page_count)
            for page_number, page_destination in enumerate(targets):
                # Entre uma página e outra é o ponto seguro para parar:
                # nada fica gravado pela metade.
                context.check_cancelled()
                self._render_page(document, page_number, page_destination, target_ext)
                written.append(page_destination)
                context.report_step(page_number + 1, page_count)

        except OperationCancelled:
            # Cancelamento não é falha: as páginas já escritas são
            # descartadas e a fila trata o resto.
            discard_partial_outputs(written, created_folder)
            raise
        except PermissionError:
            discard_partial_outputs(written, created_folder)
            return _failure(
                input_path,
                "Sem permissão para gravar na pasta de destino. "
                "Escolha outra pasta nas configurações.",
            )
        except OSError as exc:
            discard_partial_outputs(written, created_folder)
            logger.exception("Erro de sistema ao converter PDF %s", input_path)
            detail = getattr(exc, "strerror", None) or str(exc)
            return _failure(input_path, f"Não foi possível gravar as imagens ({detail}).")
        except Exception:  # noqa: BLE001 — a UI nunca deve receber um traceback
            discard_partial_outputs(written, created_folder)
            logger.exception("Falha inesperada ao converter PDF %s", input_path)
            return _failure(
                input_path,
                "Erro inesperado ao converter este PDF. Veja os logs para detalhes.",
            )
        finally:
            if document is not None:
                document.close()

        logger.info(
            "Conversão concluída | PyMuPDF | %s -> %d página(s) .%s | %.2fs",
            get_filename(source),
            len(written),
            target_ext,
            time.monotonic() - started_at,
        )
        # Com várias páginas o resultado é a pasta que as contém; com uma
        # página só, o próprio arquivo pedido.
        produced = written[0] if len(written) == 1 else written[0].parent
        return ConversionResult(success=True, input_path=input_path, output_path=str(produced))

    def _render_page(
        self, document, page_number: int, destination: Path, target_ext: str
    ) -> None:
        page = document[page_number]
        zoom = render_zoom(page.rect.width, page.rect.height, target_ext)
        if zoom < PDF_RENDER_DPI / 72:
            logger.info(
                "Página %d grande demais para %d dpi; rasterizada a %.0f dpi",
                page_number + 1,
                PDF_RENDER_DPI,
                zoom * 72,
            )
        # Matriz, e não `dpi=`: o PyMuPDF só aceita dpi inteiro, e o fator
        # reduzido de uma página enorme quase nunca é.
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        mode = "RGBA" if pixmap.alpha else "RGB"
        image = Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples)
        if target_ext in FORMATS_WITHOUT_ALPHA and has_alpha(image):
            image = flatten_onto_background(image)

        temp_output = temp_output_path(destination)
        try:
            image.save(
                temp_output, format=PILLOW_FORMAT[target_ext], **save_options(image, target_ext)
            )
            temp_output.replace(destination)
        except BaseException:
            temp_output.unlink(missing_ok=True)
            raise
