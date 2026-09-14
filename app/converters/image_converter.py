"""
Conversor de imagens baseado em Pillow.

Implementa a interface `BaseConverter` (app/core/converter.py) e é
registrado na camada de compatibilidade por
`app.converters.register_builtin_converters`, o que faz o seletor de
formato da interface oferecer opções verdadeiras para arquivos de imagem.

Formatos: PNG, JPG/JPEG e WEBP, em qualquer combinação. BMP, TIFF e GIF
são reconhecidos pelo aplicativo mas ainda não têm conversão — enquanto
não estiverem implementados e testados aqui, a interface não oferece
essas conversões, em vez de fingir que elas existem.

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

from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

from app.core.converter import BaseConverter, ConversionResult, refuse_overwriting_source
from app.core.task_context import NULL_CONTEXT, OperationCancelled, TaskContext
from app.utils.file_utils import (
    ensure_directory,
    get_extension,
    get_filename,
    temp_output_path,
)
from app.utils.logger import get_logger

logger = get_logger("converters.image")

# Formatos de imagem cobertos. As duas listas ficam separadas porque
# nem tudo que sabemos ler é oferecido como destino.
SOURCE_FORMATS: set[str] = {"png", "jpg", "jpeg", "webp"}

# 'jpeg' fica de fora dos destinos de propósito: é o mesmo formato que
# 'jpg', e listar os dois faria o seletor mostrar duas opções idênticas
# ao usuário. Como extensão de saída pedida explicitamente, porém, ela
# continua sendo aceita (ver `_WRITABLE_FORMATS`).
TARGET_FORMATS: set[str] = {"png", "jpg", "webp"}

# O nome do formato usado pelo Pillow nem sempre é igual à extensão
# ('jpg' -> 'JPEG'), então a tradução é explícita. É público porque o
# conversor de PDF grava as páginas renderizadas com as mesmas regras.
PILLOW_FORMAT: dict[str, str] = {
    "png": "PNG",
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "webp": "WEBP",
}

# Extensões de saída que este conversor sabe gravar — inclui o apelido
# 'jpeg', que não é oferecido no seletor mas funciona se for pedido.
_WRITABLE_FORMATS: set[str] = set(PILLOW_FORMAT)

# Formatos sem canal de transparência: a imagem precisa ser achatada
# sobre um fundo antes de salvar, senão o Pillow recusa a gravação.
_FORMATS_WITHOUT_ALPHA: set[str] = {"jpg", "jpeg"}

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


def _prepare_image(image: Image.Image, target_ext: str) -> Image.Image:
    """Ajusta orientação e modo de cor da imagem para o formato de destino."""
    # Fotos de celular costumam vir "deitadas", com a rotação correta
    # apenas na tag EXIF. A rotação é aplicada aos pixels aqui, e é por
    # isso que a tag precisa sair do EXIF gravado (ver
    # `exif_without_orientation`).
    image = ImageOps.exif_transpose(image) or image

    if target_ext in _FORMATS_WITHOUT_ALPHA and has_alpha(image):
        return flatten_onto_background(image)

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


def save_options(
    image: Image.Image, target_ext: str, source: Image.Image | None = None
) -> dict:
    """Parâmetros de gravação por formato, incluindo os metadados que
    vale a pena preservar (EXIF e perfil de cor ICC).

    `image` é a imagem que vai ser gravada; `source`, a imagem de onde ela
    saiu, quando são diferentes — é da origem que vêm os metadados.
    """
    options: dict = {}
    source = source if source is not None else image

    if target_ext in ("jpg", "jpeg"):
        options.update(quality=JPEG_QUALITY, optimize=True, progressive=True)
    elif target_ext == "webp":
        options.update(quality=WEBP_QUALITY, method=6)
    elif target_ext == "png":
        options.update(optimize=True)

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


class ImageConverter(BaseConverter):
    """Converte imagens entre PNG, JPG/JPEG e WEBP usando Pillow.

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

        temp_output: Path | None = None
        try:
            # A conversão de uma imagem é indivisível: ou vale a pena
            # começar, ou não. O ponto seguro para desistir é antes de
            # abrir o arquivo — depois disso, parar no meio só deixaria
            # trabalho pela metade sem economizar tempo real.
            context.check_cancelled()
            ensure_directory(destination.parent)

            # Gravação atômica: escreve no temporário e só então move.
            temp_output = temp_output_path(destination)

            with Image.open(source) as image:
                prepared = _prepare_image(image, target_ext)
                prepared.save(
                    temp_output,
                    format=PILLOW_FORMAT[target_ext],
                    **save_options(prepared, target_ext, source=image),
                )

            temp_output.replace(destination)
            temp_output = None

        except OperationCancelled:
            # Cancelamento não é falha: sobe para a fila tratar, e o
            # `finally` abaixo ainda apaga o temporário pela metade.
            raise
        except UnidentifiedImageError:
            return self._failure(
                input_path,
                f"'{get_filename(source)}' não é uma imagem válida ou está corrompido.",
            )
        except PermissionError:
            return self._failure(
                input_path,
                "Sem permissão para gravar na pasta de destino. "
                "Escolha outra pasta nas configurações.",
            )
        except OSError as exc:
            logger.exception("Erro de sistema ao converter %s", input_path)
            detail = getattr(exc, "strerror", None) or str(exc)
            return self._failure(
                input_path, f"Não foi possível gravar o arquivo convertido ({detail})."
            )
        except Exception:  # noqa: BLE001 — a UI nunca deve receber um traceback
            logger.exception("Falha inesperada ao converter %s", input_path)
            return self._failure(
                input_path,
                "Erro inesperado ao converter esta imagem. Veja os logs para detalhes.",
            )
        finally:
            # Um temporário que sobrou significa falha no meio do
            # caminho; ele não pode ficar sujando a pasta do usuário.
            if temp_output is not None:
                temp_output.unlink(missing_ok=True)

        context.report(100)
        elapsed = time.monotonic() - started_at
        logger.info(
            "Conversão concluída | Pillow | %s -> %s | %.2fs",
            get_filename(source),
            get_filename(destination),
            elapsed,
        )
        return ConversionResult(
            success=True, input_path=input_path, output_path=str(destination)
        )

    def _failure(self, input_path: str, message: str) -> ConversionResult:
        logger.warning("Conversão falhou | %s | %s", get_filename(input_path), message)
        return ConversionResult(success=False, input_path=input_path, error_message=message)
