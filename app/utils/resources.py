"""
Localização dos arquivos de recurso do FileMorph (ícone e mascote).

Em desenvolvimento os recursos ficam em `assets/`, ao lado do `main.py`.
Empacotado com PyInstaller, eles passam a viver ao lado do executável,
na pasta apontada por `sys._MEIPASS`. Este módulo esconde essa diferença: o resto do
aplicativo pede um caminho e não precisa saber em qual dos dois mundos
está rodando — a mesma preocupação que `app/config/settings.py` já tem
com a pasta de dados do usuário.

**Nada aqui levanta exceção por arquivo ausente.** `get_asset` devolve
None, e quem chama decide o que fazer. É isso que torna a arte
substituível sem tocar em código: trocar o mascote é sobrescrever o PNG
em `assets/mascot/ditto.png`, e removê-lo apenas faz a janela abrir sem
a figura, em vez de quebrar.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Caminhos relativos a `assets/`, em um lugar só para não ficarem
# espalhados como texto solto pela interface.
MASCOT_PATH = ("mascot", "ditto.png")
ICON_PATH = ("icons", "filemorph.ico")


def get_assets_dir() -> Path:
    """Pasta raiz dos recursos, em desenvolvimento ou empacotado."""
    empacotado = getattr(sys, "_MEIPASS", None)
    if empacotado:
        return Path(empacotado) / "assets"
    # app/utils/resources.py -> app/utils -> app -> raiz do projeto
    return Path(__file__).resolve().parent.parent.parent / "assets"


def get_asset(*parts: str) -> Path | None:
    """Caminho de um recurso, ou None se ele não estiver lá."""
    caminho = get_assets_dir().joinpath(*parts)
    return caminho if caminho.is_file() else None
