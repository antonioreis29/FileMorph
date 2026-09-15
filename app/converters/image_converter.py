"""
Conversor de imagens baseado em Pillow.

Implementa a interface `BaseConverter` (app/core/converter.py) e é
registrado na camada de compatibilidade por
`app.converters.register_builtin_converters`, o que faz o seletor de
formato da interface oferecer opções verdadeiras para arquivos de imagem.

Formatos: PNG, JPG/JPEG, WEBP, BMP, TIFF/TIF e GIF, em qualquer
combinação.

Arquivos com mais de um quadro seguem a natureza de cada formato:

- TIFF de várias páginas (o formato comum de digitalizações) é tratado
  como documento: para TIFF, continua um arquivo só com todas as
  páginas; para qualquer outro formato, vira uma pasta com uma imagem
  por página, do mesmo jeito que um PDF de várias páginas.
- GIF, WEBP ou PNG animados continuam animados quando o destino é GIF
  ou WEBP. Para um formato sem animação, fica o primeiro quadro.

Cuidados que este módulo garante:

- O arquivo de origem nunca é modificado nem apagado: ele é
  aberto somente para leitura.
- A gravação é atômica: a imagem é escrita em um arquivo temporário na
  pasta de destino e só depois movida para o nome final. Assim, uma
  falha no meio da gravação nunca deixa um arquivo de saída truncado —
  nem destrói um arquivo que já existisse com aquele nome.
- Nenhuma exceção escapa para a interface: qualquer erro vira um
  `ConversionResult(success=False)` com mensagem em português, e o
  traceback completo vai para o log.
"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import ExifTags, Image, ImageOps, ImageSequence, UnidentifiedImageError

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

logger = get_logger("converters.image")

# Formatos de imagem cobertos. As duas listas ficam separadas porque
# nem tudo que sabemos ler é oferecido como destino.
SOURCE_FORMATS: set[str] = {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "gif"}

# 'jpeg' e 'tif' ficam de fora dos destinos de propósito: são o mesmo
# formato que 'jpg' e 'tiff', e listar os dois faria o seletor mostrar
# duas opções idênticas ao usuário. Como extensão de saída pedida
# explicitamente, porém, continuam sendo aceitas (ver `_WRITABLE_FORMATS`).
TARGET_FORMATS: set[str] = {"png", "jpg", "webp", "bmp", "tiff", "gif"}

# O nome do formato usado pelo Pillow nem sempre é igual à extensão
# ('jpg' -> 'JPEG'), então a tradução é explícita. É público porque o
# conversor de PDF grava as páginas renderizadas com as mesmas regras.
PILLOW_FORMAT: dict[str, str] = {
    "png": "PNG",
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "webp": "WEBP",
    "bmp": "BMP",
    "tiff": "TIFF",
    "tif": "TIFF",
    "gif": "GIF",
}

# Extensões de saída que este conversor sabe gravar — inclui os apelidos
# 'jpeg' e 'tif', que não são oferecidos no seletor mas funcionam se
# forem pedidos.
_WRITABLE_FORMATS: set[str] = set(PILLOW_FORMAT)

# Formatos sem canal de transparência: a imagem precisa ser achatada
# sobre um fundo antes de salvar. O JPEG recusa a gravação; o BMP aceita
# e simplesmente descarta o alfa, o que deixaria à mostra a cor que
# estava "escondida" sob as áreas transparentes.
FORMATS_WITHOUT_ALPHA: set[str] = {"jpg", "jpeg", "bmp"}

# Destinos que guardam animação num arquivo só.
_ANIMATED_TARGETS: set[str] = {"gif", "webp"}

# O GIF só conhece pixel totalmente transparente ou totalmente opaco.
# Um pixel a partir desta opacidade vira opaco (composto sobre o fundo);
# abaixo dela, transparente.
_GIF_ALPHA_THRESHOLD = 128

# Cor usada ao achatar transparência (branco é o que o usuário espera
# ao mandar um PNG recortado virar JPG).
_FLATTEN_BACKGROUND = (255, 255, 255)

# Qualidade da compressão com perdas — alta o suficiente para que a
# conversão não seja visivelmente destrutiva no uso comum.
JPEG_QUALITY = 95
WEBP_QUALITY = 90

# Modos de imagem que cada formato de destino aceita gravar diretamente.
# Qualquer outro modo (CMYK, I;16, paleta...) é convertido antes.
_MODES_SUPPORTED: dict[str, set[str]] = {
    "png": {"1", "L", "LA", "I", "P", "RGB", "RGBA"},
    "jpg": {"L", "RGB", "CMYK"},
    "jpeg": {"L", "RGB", "CMYK"},
    "webp": {"RGB", "RGBA"},
    "bmp": {"1", "L", "P", "RGB"},
    # O Pillow reduz RGB e RGBA à paleta de 256 cores do GIF sozinho.
    "gif": {"1", "L", "P", "RGB", "RGBA"},
    # Sem 'P': o TIFF grava a paleta, mas não o índice transparente dela.
    "tiff": {"1", "L", "LA", "I", "I;16", "F", "RGB", "RGBA", "CMYK"},
    "tif": {"1", "L", "LA", "I", "I;16", "F", "RGB", "RGBA", "CMYK"},
}


def has_alpha(image: Image.Image) -> bool:
    """True se a imagem carrega transparência, seja por canal alfa ou
    por índice transparente numa paleta."""
    if image.mode in ("RGBA", "LA", "PA"):
        return True
    return image.mode == "P" and "transparency" in image.info


def flatten_onto_background(image: Image.Image) -> Image.Image:
    """Compõe a imagem sobre um fundo opaco preservando as cores das
    áreas semitransparentes — por isso a composição usa o próprio canal
    alfa como máscara, em vez de um simples convert('RGB')."""
    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, _FLATTEN_BACKGROUND)
    background.paste(rgba, mask=rgba.split()[-1])
    return background


def _binary_alpha(image: Image.Image) -> Image.Image:
    """Prepara a transparência para o GIF, que não tem meio-termo.

    Deixado com o Pillow, todo pixel que não é totalmente transparente
    vira a própria cor, opaca: a sombra suave de um logotipo sai como uma
    mancha preta. Aqui o que é quase transparente some, e o resto é
    composto sobre o fundo antes de perder a transparência parcial.
    """
    alpha = image.convert("RGBA").getchannel("A")
    flat = flatten_onto_background(image)
    flat.putalpha(alpha.point(lambda value: 255 if value >= _GIF_ALPHA_THRESHOLD else 0))
    return flat


def _prepare_image(image: Image.Image, target_ext: str) -> Image.Image:
    """Ajusta orientação e modo de cor da imagem para o formato de destino."""
    # Fotos de celular costumam vir "deitadas", com a rotação correta
    # apenas na tag EXIF. A rotação é aplicada aos pixels aqui, e é por
    # isso que a tag precisa sair do EXIF gravado (ver
    # `exif_without_orientation`).
    image = ImageOps.exif_transpose(image) or image

    if target_ext in FORMATS_WITHOUT_ALPHA and has_alpha(image):
        return flatten_onto_background(image)
    if target_ext == "gif" and has_alpha(image):
        return _binary_alpha(image)

    supported = _MODES_SUPPORTED.get(target_ext, {"RGB", "RGBA"})
    if image.mode in supported:
        return image
    return image.convert("RGBA" if has_alpha(image) else "RGB")


# Espaço de cor de cada modo do Pillow, para saber se um perfil ICC ainda
# descreve a imagem depois da conversão de modo. Um modo fora da tabela só
# combina com ele mesmo.
_COLOR_SPACE_BY_MODE: dict[str, str] = {
    "1": "gray",
    "L": "gray",
    "LA": "gray",
    "I": "gray",
    "I;16": "gray",
    "F": "gray",
    "P": "rgb",
    "PA": "rgb",
    "RGB": "rgb",
    "RGBA": "rgb",
    "RGBX": "rgb",
    "CMYK": "cmyk",
}


def exif_without_orientation(image: Image.Image) -> bytes | None:
    """O EXIF da imagem, sem a tag de orientação, pronto para gravar.

    Quando a rotação da tag já foi aplicada aos pixels, repassar o EXIF
    original deixaria no arquivo novo uma imagem de pé *e* uma tag dizendo
    "gire 90°" — e todo visualizador que respeita a tag (o do Windows, o
    do celular, o navegador) giraria de novo. A tag sai; o resto fica:
    data, câmera, GPS, que é o que faz a foto continuar sendo aquela foto.

    Os blocos internos do EXIF (o de dados da câmera e o de GPS) são lidos
    antes de regravar, para irem junto.
    """
    if not image.info.get("exif"):
        return None
    exif = image.getexif()
    for ifd in (ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo):
        if ifd in exif:
            exif.get_ifd(ifd)
    exif.pop(ExifTags.Base.Orientation, None)
    return exif.tobytes()


def _icc_matches(source_mode: str, target_mode: str) -> bool:
    """True se um perfil de cor da origem ainda serve para a imagem gravada.

    Um perfil CMYK anexado a um PNG que virou RGB — ou um perfil de cinza a
    um WEBP colorido — descreveria cores que a imagem não tem, e o
    visualizador as mostraria erradas. Melhor gravar sem perfil nesse caso.
    """
    return _COLOR_SPACE_BY_MODE.get(source_mode, source_mode) == _COLOR_SPACE_BY_MODE.get(
        target_mode, target_mode
    )


def _encoding_options(target_ext: str) -> dict:
    """Qualidade e compressão de cada formato, sem metadados."""
    if target_ext in ("jpg", "jpeg"):
        return {"quality": JPEG_QUALITY, "optimize": True, "progressive": True}
    if target_ext == "webp":
        return {"quality": WEBP_QUALITY, "method": 6}
    if target_ext == "png":
        return {"optimize": True}
    if target_ext in ("tiff", "tif"):
        # Sem compressão, o TIFF de uma foto comum passa fácil de 30 MB.
        # O LZW não perde nada e todo programa que abre TIFF o entende.
        return {"compression": "tiff_lzw"}
    return {}


def save_options(
    image: Image.Image, target_ext: str, source: Image.Image | None = None
) -> dict:
    """Parâmetros de gravação por formato, incluindo os metadados que
    vale a pena preservar (EXIF e perfil de cor ICC).

    `image` é a imagem que vai ser gravada; `source`, a imagem de onde ela
    saiu, quando são diferentes — é da origem que vêm os metadados.
    """
    options = _encoding_options(target_ext)
    source = source if source is not None else image

    # O TIFF fica de fora: com a compressão LZW, a gravação passa pelo
    # libtiff, que recusa os blocos internos do EXIF (câmera e GPS).
    if target_ext in ("jpg", "jpeg", "webp"):
        exif = exif_without_orientation(source)
        if exif:
            options["exif"] = exif

    icc_profile = source.info.get("icc_profile")
    if icc_profile and _icc_matches(source.mode, image.mode):
        options["icc_profile"] = icc_profile
    elif icc_profile:
        # Explícito, e não só ausente: a conversão de modo copia o `info` da
        # origem, e o gravador de PNG usa o perfil de lá quando a opção não
        # é passada.
        options["icc_profile"] = None

    return options


def frame_count(image: Image.Image) -> int:
    return getattr(image, "n_frames", 1)


def is_multipage_tiff(image: Image.Image) -> bool:
    return image.format == "TIFF" and frame_count(image) > 1


def _keeps_all_frames(image: Image.Image, target_ext: str) -> bool:
    """True quando todos os quadros cabem juntos num arquivo de destino."""
    if frame_count(image) <= 1:
        return False
    if image.format == "TIFF":
        return target_ext in ("tiff", "tif")
    return target_ext in _ANIMATED_TARGETS


def _write_image(
    image: Image.Image, destination: Path, target_ext: str, all_frames: bool = False
) -> None:
    """Grava a imagem de forma atômica: no temporário e só então no nome final.

    Com `all_frames`, o Pillow percorre os quadros sozinho e cada um é
    convertido por ele; os metadados ficam de fora, porque a rotação do
    EXIF não é aplicada quadro a quadro e repassá-la mudaria a imagem.
    """
    temp_output = temp_output_path(destination)
    try:
        if all_frames:
            image.save(
                temp_output,
                format=PILLOW_FORMAT[target_ext],
                save_all=True,
                **_encoding_options(target_ext),
            )
        else:
            prepared = _prepare_image(image, target_ext)
            prepared.save(
                temp_output,
                format=PILLOW_FORMAT[target_ext],
                **save_options(prepared, target_ext, source=image),
            )
        temp_output.replace(destination)
    except BaseException:
        # Um temporário que sobrou significa falha no meio do caminho;
        # ele não pode ficar sujando a pasta do usuário.
        temp_output.unlink(missing_ok=True)
        raise


class ImageConverter(BaseConverter):
    """Converte imagens entre PNG, JPG, WEBP, BMP, TIFF e GIF usando Pillow.

    A interface não sabe (nem precisa saber) que existe Pillow por trás
    disso — ela apenas pede "converta este arquivo para .webp" através
    do `FileProcessor`.
    """

    @property
    def source_formats(self) -> set[str]:
        return set(SOURCE_FORMATS)

    @property
    def target_formats(self) -> set[str]:
        return set(TARGET_FORMATS)

    def convert(
        self, input_path: str, output_path: str, context: TaskContext | None = None
    ) -> ConversionResult:
        context = context or NULL_CONTEXT
        source = Path(input_path)
        destination = Path(output_path)
        target_ext = get_extension(destination)
        started_at = time.monotonic()

        if target_ext not in _WRITABLE_FORMATS:
            return self._failure(
                input_path,
                f"O FileMorph ainda não sabe gravar imagens em .{target_ext}.",
            )

        if not source.is_file():
            return self._failure(
                input_path, f"O arquivo '{get_filename(source)}' não foi encontrado."
            )
        refused = refuse_overwriting_source(input_path, output_path)
        if refused is not None:
            return refused

        written: list[Path] = []
        created_folder: Path | None = None
        try:
            # O ponto seguro para desistir de uma imagem é antes de abrir o
            # arquivo — depois disso, parar no meio só deixaria trabalho
            # pela metade sem economizar tempo real. Um TIFF de várias
            # páginas é a exceção: cada página é um ponto seguro.
            context.check_cancelled()

            with Image.open(source) as image:
                if is_multipage_tiff(image) and not _keeps_all_frames(image, target_ext):
                    total = frame_count(image)
                    created_folder, targets = page_destinations(destination, total)
                    for index, page in enumerate(ImageSequence.Iterator(image)):
                        context.check_cancelled()
                        _write_image(page, targets[index], target_ext)
                        written.append(targets[index])
                        context.report_step(index + 1, total)
                else:
                    ensure_directory(destination.parent)
                    _write_image(
                        image,
                        destination,
                        target_ext,
                        all_frames=_keeps_all_frames(image, target_ext),
                    )

        except OperationCancelled:
            # Cancelamento não é falha: as páginas já gravadas saem, e a
            # fila trata o resto.
            discard_partial_outputs(written, created_folder)
            raise
        except UnidentifiedImageError:
            return self._failure(
                input_path,
                f"'{get_filename(source)}' não é uma imagem válida ou está corrompido.",
            )
        except PermissionError:
            discard_partial_outputs(written, created_folder)
            return self._failure(
                input_path,
                "Sem permissão para gravar na pasta de destino. "
                "Escolha outra pasta nas configurações.",
            )
        except OSError as exc:
            discard_partial_outputs(written, created_folder)
            logger.exception("Erro de sistema ao converter %s", input_path)
            detail = getattr(exc, "strerror", None) or str(exc)
            return self._failure(
                input_path, f"Não foi possível gravar o arquivo convertido ({detail})."
            )
        except Exception:  # noqa: BLE001 — a UI nunca deve receber um traceback
            discard_partial_outputs(written, created_folder)
            logger.exception("Falha inesperada ao converter %s", input_path)
            return self._failure(
                input_path,
                "Erro inesperado ao converter esta imagem. Veja os logs para detalhes.",
            )

        context.report(100)
        elapsed = time.monotonic() - started_at
        # Com várias páginas o resultado é a pasta que as contém.
        produced = created_folder if created_folder is not None else destination
        logger.info(
            "Conversão concluída | Pillow | %s -> %s | %.2fs",
            get_filename(source),
            get_filename(produced),
            elapsed,
        )
        return ConversionResult(success=True, input_path=input_path, output_path=str(produced))

    def _failure(self, input_path: str, message: str) -> ConversionResult:
        logger.warning("Conversão falhou | %s | %s", get_filename(input_path), message)
        return ConversionResult(success=False, input_path=input_path, error_message=message)
