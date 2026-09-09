"""
Conversores de PDF (FASE 4 do briefing).

Duas direções, cada uma em sua classe, porque são operações bem
diferentes por dentro:

- `ImageToPdfConverter` — uma imagem vira um PDF de uma página (Pillow).
- `PdfToImageConverter` — um PDF vira imagens, uma por página (PyMuPDF
  para renderizar, Pillow para gravar com as mesmas regras de qualidade
  usadas no conversor de imagens).

Como no Fase 3, a interface não sabe qual biblioteca está por trás:
ela só pede "converta este arquivo para .pdf" e recebe de volta um
`ConversionResult` (item 4).

Sobre PDFs com várias páginas: um PDF de página única vira exatamente
o arquivo pedido. Um PDF com várias páginas viraria dezenas de
arquivos soltos na pasta de saída, então as páginas vão para uma
subpasta com o nome do documento (`relatorio/relatorio_p01.png`, ...).
Se já existir uma pasta com esse nome, uma nova é criada com sufixo
numérico, para nunca sobrescrever um resultado anterior (item 21).
"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.converters.image_converter import (
    PILLOW_FORMAT,
    flatten_onto_background,
    has_alpha,
    save_options,
)
from app.core.converter import BaseConverter, ConversionResult
from app.core.task_context import NULL_CONTEXT, OperationCancelled, TaskContext
from app.utils.file_utils import (
    ensure_directory,
    get_extension,
    get_filename,
    get_stem,
    get_unique_path,
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

# Imagens que sabemos transformar em página de PDF.
IMAGE_SOURCE_FORMATS: set[str] = {"png", "jpg", "jpeg", "webp"}

# Formatos de imagem que sabemos gerar a partir de um PDF.
IMAGE_TARGET_FORMATS: set[str] = {"png", "jpg", "webp"}

# Resolução usada para rasterizar uma página de PDF. 150 dpi é o meio
# termo entre legibilidade (dá para ler texto pequeno) e tamanho de
# arquivo — 300 dpi quadruplica os bytes sem ganho perceptível na tela.
PDF_RENDER_DPI = 150

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
    """Transforma uma imagem em um PDF de página única (Pillow).

    A página fica do tamanho exato da imagem, sem recorte nem
    redimensionamento: se a imagem declara DPI, ele é respeitado; caso
    contrário, assume-se 72 dpi.
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

        temp_output: Path | None = None
        try:
            context.check_cancelled()
            ensure_directory(destination.parent)
            temp_output = temp_output_path(destination)

            with Image.open(source) as image:
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

        document = None
        written: list[Path] = []
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

            targets = self._page_destinations(destination, page_count)
            for page_number, page_destination in enumerate(targets):
                # Entre uma página e outra é o ponto seguro para parar:
                # nada fica gravado pela metade (item 17).
                context.check_cancelled()
                self._render_page(document, page_number, page_destination, target_ext)
                written.append(page_destination)
                context.report_step(page_number + 1, page_count)

        except OperationCancelled:
            # Cancelamento não é falha: as páginas já escritas são
            # descartadas e a fila trata o resto.
            self._discard(written)
            raise
        except PermissionError:
            self._discard(written)
            return _failure(
                input_path,
                "Sem permissão para gravar na pasta de destino. "
                "Escolha outra pasta nas configurações.",
            )
        except OSError as exc:
            self._discard(written)
            logger.exception("Erro de sistema ao converter PDF %s", input_path)
            detail = getattr(exc, "strerror", None) or str(exc)
            return _failure(input_path, f"Não foi possível gravar as imagens ({detail}).")
        except Exception:  # noqa: BLE001 — a UI nunca deve receber um traceback
            self._discard(written)
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

    def _page_destinations(self, destination: Path, page_count: int) -> list[Path]:
        """Onde cada página vai ser gravada.

        Uma página: exatamente o caminho pedido, que já passou pelo
        fluxo de conflito de nomes da interface. Várias páginas: uma
        subpasta nova com o nome do documento."""
        if page_count == 1:
            ensure_directory(destination.parent)
            return [destination]

        stem = get_stem(destination)
        folder = get_unique_path(destination.parent / stem)
        ensure_directory(folder)
        width = max(2, len(str(page_count)))
        return [
            folder / f"{stem}_p{number:0{width}d}{destination.suffix}"
            for number in range(1, page_count + 1)
        ]

    def _render_page(
        self, document, page_number: int, destination: Path, target_ext: str
    ) -> None:
        pixmap = document[page_number].get_pixmap(dpi=PDF_RENDER_DPI)
        mode = "RGBA" if pixmap.alpha else "RGB"
        image = Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples)
        if target_ext in ("jpg", "jpeg") and has_alpha(image):
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

    @staticmethod
    def _discard(written: list[Path]) -> None:
        """Uma conversão que falhou no meio não deixa páginas soltas pela
        metade na pasta do usuário — nem a subpasta vazia que as abrigava."""
        folders = {path.parent for path in written}
        for path in written:
            try:
                path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover — arquivo em uso, por exemplo
                logger.warning("Não foi possível remover a página parcial %s", path)
        for folder in folders:
            try:
                folder.rmdir()  # só remove se tiver ficado vazia
            except OSError:
                pass
