"""
Carregamento do mascote para a interface.

Fica no lado da UI, e não em `app/utils/`, porque depende de Qt
(`QPixmap`) — o pacote `utils` é mantido livre de Qt para que os
conversores possam ser testados sem interface.

Duas decisões deliberadas, ambas para tornar a troca da arte um
arrastar de arquivo em vez de uma mudança de código:

- **O nome do arquivo não importa muito.** `ditto.png` é o preferido,
  mas se ele não existir qualquer imagem na pasta serve. Assim, jogar um
  PNG baixado direto em `assets/mascot/` já funciona.
- **Nada é obrigatório.** Sem imagem, a janela abre sem a figura, em vez
  de quebrar.

Sobre a ampliação: `FastTransformation` é a interpolação por vizinho
mais próximo, a única que preserva a borda dura do pixel art. A
suavização que o Qt usa por padrão transformaria qualquer sprite em um
borrão.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from app.utils.logger import get_logger
from app.utils.resources import MASCOT_PATH, get_asset, get_assets_dir

logger = get_logger("ui.mascot")

# Formatos que o Qt lê sem plugin extra.
_EXTENSOES = (".png", ".webp", ".gif", ".jpg", ".jpeg", ".bmp")


def find_mascot_file() -> Path | None:
    """O arquivo do mascote: `ditto.png` se existir, senão a primeira
    imagem que estiver na pasta."""
    preferido = get_asset(*MASCOT_PATH)
    if preferido is not None:
        return preferido

    pasta = get_assets_dir() / MASCOT_PATH[0]
    if not pasta.is_dir():
        return None

    candidatos = sorted(
        p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() in _EXTENSOES
    )
    if candidatos:
        logger.info(
            "Usando '%s' como mascote (renomeie para ditto.png para fixar a escolha).",
            candidatos[0].name,
        )
        return candidatos[0]
    return None


def load_mascot_pixmap(height: int) -> QPixmap | None:
    """O mascote pronto para exibir, com a altura pedida, ou None."""
    caminho = find_mascot_file()
    if caminho is None:
        logger.info(
            "Nenhuma imagem em assets/%s — a janela abre sem o mascote.", MASCOT_PATH[0]
        )
        return None

    pixmap = QPixmap(str(caminho))
    if pixmap.isNull():
        logger.warning("'%s' não pôde ser lido como imagem.", caminho)
        return None

    return pixmap.scaledToHeight(height, Qt.TransformationMode.FastTransformation)
