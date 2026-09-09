"""
Registro dos conversores concretos disponíveis (FASE 3).

Este pacote é o único lugar que sabe *quais* conversores existem de
fato. O restante do aplicativo conversa apenas com a camada de
compatibilidade (`app.core.converter.compatibility_registry`), que é
preenchida aqui na inicialização (ver `main.py`).

A checagem de dependência é intencional: se a biblioteca necessária
não estiver instalada nesta máquina, o conversor simplesmente não é
registrado — e a interface, que só oferece o que está registrado,
continua honesta em vez de apresentar uma opção que falharia na hora
de converter (item 37).
"""

from __future__ import annotations

import weakref

from app.core.converter import CompatibilityRegistry, compatibility_registry
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

    _registered_into.add(target)

    if registered:
        logger.info("Conversores registrados: %s", ", ".join(registered))
    else:
        logger.warning("Nenhum conversor disponível nesta instalação.")

    return registered
