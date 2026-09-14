"""
Registro dos mergers concretos disponíveis.

Espelha `app/converters/__init__.py`: é o único lugar que sabe quais
junções existem de fato, e só registra as que têm sua biblioteca
instalada. O restante do aplicativo pergunta ao
`app.core.merger.merge_compatibility_registry`, que é preenchido aqui
na inicialização (ver `main.py`).
"""

from __future__ import annotations

import weakref

from app.core.merger import MergeCompatibilityRegistry, merge_compatibility_registry
from app.utils.libreoffice_manager import LibreOfficeManager
from app.utils.logger import get_logger

logger = get_logger("mergers")

# Registros já preenchidos, para que uma segunda chamada não duplique
# mergers. É um WeakSet para não manter vivo um registro de teste
# depois que ele sai de escopo.
_registered_into: weakref.WeakSet[MergeCompatibilityRegistry] = weakref.WeakSet()


def register_builtin_mergers(
    registry: MergeCompatibilityRegistry | None = None,
    *,
    libreoffice: LibreOfficeManager | None = None,
) -> list[str]:
    """Registra todos os mergers implementados e disponíveis.

    Retorna os nomes dos mergers registrados, para log e diagnóstico. É
    idempotente, e aceita um registro isolado e um LibreOffice de mentira
    para os testes.
    """
    target = registry if registry is not None else merge_compatibility_registry

    if target in _registered_into:
        return []

    registered: list[str] = []

    # --- PDF e imagens -> PDF (pypdf + Pillow) ---------------------------
    try:
        from app.mergers.pdf_merger import PYPDF_AVAILABLE, PdfMerger
    except ImportError as exc:
        logger.warning("Junção de PDFs indisponível (%s).", exc)
    else:
        if PYPDF_AVAILABLE:
            target.register(PdfMerger(libreoffice))
            registered.append("PdfMerger (pypdf)")
        else:
            logger.warning(
                "pypdf não está instalado — a junção de arquivos ficará "
                "indisponível nesta execução."
            )

    _registered_into.add(target)

    if registered:
        logger.info("Mergers registrados: %s", ", ".join(registered))
    else:
        logger.warning("Nenhuma junção disponível nesta instalação.")

    return registered
