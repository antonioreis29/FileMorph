"""
Registro dos conversores concretos disponíveis.

Este pacote é o único lugar que sabe *quais* conversores existem de
fato. O restante do aplicativo conversa apenas com a camada de
compatibilidade (`app.core.converter.compatibility_registry`), que é
preenchida aqui na inicialização (ver `main.py`).

A checagem de dependência é intencional: se a biblioteca necessária
não estiver instalada nesta máquina, o conversor simplesmente não é
registrado — e a interface, que só oferece o que está registrado,
continua honesta em vez de apresentar uma opção que falharia na hora
de converter (item 37).

A partir da Fase 6 a checagem vai um passo além para áudio e vídeo:
não basta o FFmpeg existir, ele precisa ter os codificadores daquele
formato compilados. Um conversor pode acabar registrado oferecendo
apenas parte dos seus destinos.

A Fase 7 acrescentou o segundo programa externo do projeto, o
LibreOffice, e com ele um caso novo: uma mesma família de formato
(documentos) tem conversões que são Python puro e uma — DOCX para PDF —
que depende do programa externo. Elas são decididas em blocos separados,
de modo que a ausência do LibreOffice tira apenas aquele destino do
seletor, sem levar as outras conversões de documento com ele.
"""

from __future__ import annotations

import weakref

from app.core.converter import CompatibilityRegistry, compatibility_registry
from app.utils.ffmpeg_manager import ffmpeg_manager
from app.utils.libreoffice_manager import libreoffice_manager
from app.utils.logger import get_logger

logger = get_logger("converters")

# Registros já preenchidos, para que uma segunda chamada não duplique
# conversores. É um WeakSet para não manter vivo um registro de teste
# depois que ele sai de escopo.
_registered_into: weakref.WeakSet[CompatibilityRegistry] = weakref.WeakSet()


def register_builtin_converters(
    registry: CompatibilityRegistry | None = None,
) -> list[str]:
    """Registra todos os conversores implementados e disponíveis.

    Retorna os nomes dos conversores registrados, para log e
    diagnóstico. É idempotente: chamar duas vezes para o mesmo registro
    não duplica conversores.

    O parâmetro `registry` existe para os testes poderem usar um
    registro isolado; a aplicação usa o registro global compartilhado.
    """
    target = registry if registry is not None else compatibility_registry

    if target in _registered_into:
        return []

    registered: list[str] = []

    # --- Imagens (Pillow) ------------------------------------------------
    try:
        from app.converters.image_converter import ImageConverter
    except ImportError as exc:
        logger.warning(
            "Pillow não está instalado — conversões de imagem ficarão "
            "indisponíveis nesta execução (%s).",
            exc,
        )
    else:
        target.register(ImageConverter())
        registered.append("ImageConverter (Pillow)")

    # --- PDF (Pillow para escrever, PyMuPDF para ler) --------------------
    try:
        from app.converters.pdf_converter import (
            PYMUPDF_AVAILABLE,
            ImageToPdfConverter,
            PdfToImageConverter,
        )
    except ImportError as exc:
        logger.warning("Conversões de PDF indisponíveis (%s).", exc)
    else:
        # Gerar PDF a partir de imagens só depende do Pillow.
        target.register(ImageToPdfConverter())
        registered.append("ImageToPdfConverter (Pillow)")

        # Ler o PDF de volta exige o PyMuPDF; sem ele, esta metade fica
        # de fora e a interface simplesmente não oferece a operação.
        if PYMUPDF_AVAILABLE:
            target.register(PdfToImageConverter())
            registered.append("PdfToImageConverter (PyMuPDF)")
        else:
            logger.warning(
                "PyMuPDF não está instalado — converter PDF em imagens ficará "
                "indisponível nesta execução."
            )

    # --- Documentos (python-docx, PyMuPDF e LibreOffice) -----------------
    # As quatro primeiras conversões são Python puro; DOCX -> PDF é a
    # única que depende de um programa externo, e por isso é decidida em
    # separado, logo abaixo.
    try:
        from app.converters.document_converter import (
            DOCX_AVAILABLE,
            PYMUPDF_AVAILABLE as DOC_PYMUPDF_AVAILABLE,
            DocxToTextConverter,
            PdfToTextConverter,
            TextToDocxConverter,
            TextToPdfConverter,
        )
    except ImportError as exc:
        logger.warning("Conversões de documento indisponíveis (%s).", exc)
    else:
        if DOCX_AVAILABLE:
            target.register(DocxToTextConverter())
            target.register(TextToDocxConverter())
            registered.append("DocxToTextConverter (python-docx)")
            registered.append("TextToDocxConverter (python-docx)")
        else:
            logger.warning(
                "python-docx não está instalado — a leitura e a gravação de "
                "DOCX ficarão indisponíveis nesta execução."
            )

        if DOC_PYMUPDF_AVAILABLE:
            target.register(TextToPdfConverter())
            target.register(PdfToTextConverter())
            registered.append("TextToPdfConverter (PyMuPDF)")
            registered.append("PdfToTextConverter (PyMuPDF)")

    # --- Planilhas (openpyxl) --------------------------------------------
    try:
        from app.converters.spreadsheet_converter import (
            OPENPYXL_AVAILABLE,
            CsvToXlsxConverter,
            XlsxToCsvConverter,
        )
    except ImportError as exc:
        logger.warning("Conversões de planilha indisponíveis (%s).", exc)
    else:
        if OPENPYXL_AVAILABLE:
            target.register(XlsxToCsvConverter())
            target.register(CsvToXlsxConverter())
            registered.append("XlsxToCsvConverter (openpyxl)")
            registered.append("CsvToXlsxConverter (openpyxl)")
        else:
            logger.warning(
                "openpyxl não está instalado — as conversões entre XLSX e CSV "
                "ficarão indisponíveis nesta execução."
            )

    # --- Arquivos de escritório para PDF (LibreOffice) -------------------
    # Como no bloco do FFmpeg, aqui a dependência é um programa externo e
    # não um pacote pip: sem LibreOffice, "PDF" simplesmente não aparece
    # no seletor de formato para um DOCX ou um XLSX (item 37).
    if libreoffice_manager.is_available():
        from app.converters.document_converter import DocxToPdfConverter
        from app.converters.spreadsheet_converter import SpreadsheetToPdfConverter

        version = libreoffice_manager.status().version or "versão desconhecida"
        target.register(DocxToPdfConverter())
        target.register(SpreadsheetToPdfConverter())
        registered.append(f"DocxToPdfConverter (LibreOffice {version})")
        registered.append("SpreadsheetToPdfConverter (LibreOffice)")
    else:
        logger.warning(
            "LibreOffice não encontrado — converter DOCX ou XLSX em PDF ficará "
            "indisponível nesta execução."
        )

    # --- Áudio e vídeo (FFmpeg) ------------------------------------------
    # Diferente dos anteriores, este bloco não depende de um pacote pip e
    # sim de um binário externo. A checagem é dupla: primeiro se o FFmpeg
    # existe, depois quais codificadores ele traz — uma compilação enxuta
    # pode ter libmp3lame e não ter libvpx-vp9, e nesse caso o conversor
    # é registrado oferecendo só os formatos que consegue mesmo gerar.
    if ffmpeg_manager.is_available():
        from app.converters.audio_converter import AudioConverter
        from app.converters.video_converter import (
            VideoConverter,
            VideoToAudioConverter,
        )

        media_converters = (
            ("AudioConverter", AudioConverter()),
            ("VideoConverter", VideoConverter()),
            ("VideoToAudioConverter", VideoToAudioConverter()),
        )
        for name, converter in media_converters:
            targets = converter.target_formats
            if targets:
                target.register(converter)
                registered.append(f"{name} (FFmpeg: {', '.join(sorted(targets))})")
            else:
                logger.warning(
                    "%s não foi registrado: esta instalação do FFmpeg não tem "
                    "nenhum dos codificadores necessários.",
                    name,
                )
    else:
        logger.warning(
            "FFmpeg não encontrado — conversões de áudio e vídeo ficarão "
            "indisponíveis nesta execução."
        )

    _registered_into.add(target)

    if registered:
        logger.info("Conversores registrados: %s", ", ".join(registered))
    else:
        logger.warning("Nenhum conversor disponível nesta instalação.")

    return registered
