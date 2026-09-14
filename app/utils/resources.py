"""
Localização dos arquivos de recurso do FileMorph (ícone, mascote e
programas de terceiros distribuídos junto).

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
MASCOT_DIR = "mascot"
MASCOT_STEM = "ditto"

# Em que ordem disputam os arquivos chamados "ditto". O GIF vem primeiro
# porque um GIF na pasta é uma escolha deliberada de quem trocou a arte,
# enquanto o PNG é o padrão de fábrica que `tools/gerar_mascote.py`
# reescreve — a mesma regra que `app/ui/file_icons.py` usa para deixar a
# arte trazida de fora vencer a gerada, sem que a gerada precise ser
# apagada. A ordem mora aqui, e não em `app/ui/mascot.py`, porque as
# ferramentas de `tools/` também precisam dela para avisar quando o PNG
# que acabaram de gravar não vai ser o escolhido — e este módulo, ao
# contrário do da janela, não depende de Qt.
MASCOT_EXTENSOES = (".gif", ".webp", ".png", ".jpg", ".jpeg", ".bmp")
ICON_PATH = ("icons", "filemorph.ico")


def get_bundle_root() -> Path:
    """A raiz do que acompanha o aplicativo: a pasta do projeto em
    desenvolvimento, ou a pasta de dados do PyInstaller quando empacotado."""
    empacotado = getattr(sys, "_MEIPASS", None)
    if empacotado:
        return Path(empacotado)
    # app/utils/resources.py -> app/utils -> app -> raiz do projeto
    return Path(__file__).resolve().parent.parent.parent


def get_assets_dir() -> Path:
    """Pasta raiz dos recursos, em desenvolvimento ou empacotado."""
    return get_bundle_root() / "assets"


def get_vendor_dir() -> Path:
    """Pasta dos programas de terceiros distribuídos junto com o FileMorph
    (hoje, só o FFmpeg opcional em `vendor/ffmpeg`). Pode não existir."""
    return get_bundle_root() / "vendor"


def get_asset(*parts: str) -> Path | None:
    """Caminho de um recurso, ou None se ele não estiver lá."""
    caminho = get_assets_dir().joinpath(*parts)
    return caminho if caminho.is_file() else None


def get_mascot_file() -> Path | None:
    """O `ditto.*` de maior preferência que estiver instalado, ou None.

    Só olha para os arquivos com o nome preferido; procurar qualquer
    imagem solta na pasta é trabalho de `app/ui/mascot.py`, que é quem
    sabe o que o Qt desta instalação consegue abrir.
    """
    for sufixo in MASCOT_EXTENSOES:
        caminho = get_asset(MASCOT_DIR, f"{MASCOT_STEM}{sufixo}")
        if caminho is not None:
            return caminho
    return None
