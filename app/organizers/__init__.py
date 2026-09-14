"""
Registro dos organizadores de páginas concretos disponíveis.

Espelha `app/mergers/__init__.py`: é o único lugar que sabe quais
documentos podem ter as páginas reorganizadas nesta instalação, e só
registra um organizador se a biblioteca dele estiver presente. O restante
do aplicativo pergunta ao `app.core.page_organizer.page_organizer_registry`,
que é preenchido aqui na inicialização (ver `main.py`).
"""

from __future__ import annotations

import weakref

from app.core.page_organizer import PageOrganizerRegistry, page_organizer_registry
from app.utils.logger import get_logger

logger = get_logger("organizers")

# Registros já preenchidos, para que uma segunda chamada não duplique
# organizadores. É um WeakSet para não manter vivo um registro de teste
# depois que ele sai de escopo.
_registered_into: weakref.WeakSet[PageOrganizerRegistry] = weakref.WeakSet()


def register_builtin_organizers(
    registry: PageOrganizerRegistry | None = None,
) -> list[str]:
    """Registra todos os organizadores implementados e disponíveis.

    Retorna os nomes dos organizadores registrados, para log e
    diagnóstico. É idempotente, e aceita um registro isolado para os
    testes.
    """
    target = registry if registry is not None else page_organizer_registry

    if target in _registered_into:
        return []

    registered: list[str] = []

    # --- PDF (PyMuPDF) ---------------------------------------------------
    # O mesmo PyMuPDF que já rasteriza páginas no "PDF -> imagens": ele
    # desenha as miniaturas e reordena as páginas sem mexer no conteúdo.
    try:
        from app.organizers.pdf_organizer import PYMUPDF_AVAILABLE, PdfPageOrganizer
    except ImportError as exc:
        logger.warning("Organização de páginas de PDF indisponível (%s).", exc)
    else:
        if PYMUPDF_AVAILABLE:
            target.register(PdfPageOrganizer())
            registered.append("PdfPageOrganizer (PyMuPDF)")
        else:
            logger.warning(
                "PyMuPDF não está instalado — organizar as páginas de um PDF "
                "ficará indisponível nesta execução."
            )

    _registered_into.add(target)

    if registered:
        logger.info("Organizadores de páginas registrados: %s", ", ".join(registered))
    else:
        logger.warning("Nenhuma organização de páginas disponível nesta instalação.")

    return registered
