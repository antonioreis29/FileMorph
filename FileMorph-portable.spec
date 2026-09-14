# -*- mode: python ; coding: utf-8 -*-
"""
Receita do PyInstaller para o FileMorph portátil: um único .exe, sem instalar.

    pyinstaller FileMorph-portable.spec --noconfirm --distpath dist/portable --workpath build/portable

Ou `.\\empacotar.ps1 -Portatil`, que faz isso junto com o instalador.

O resultado é `dist/portable/FileMorph-<versão>-portable.exe`. É uma opção
para quem não pode instalar programas; **a distribuição recomendada continua
sendo o instalador** (`FileMorph.spec` + Inno Setup), por dois motivos:

- **Abertura mais lenta.** Um executável de arquivo único do PyInstaller
  descompacta o aplicativo inteiro (Python, Qt, bibliotecas) numa pasta
  temporária a cada vez que abre. Leva alguns segundos a mais que a versão
  instalada, e mais ainda na primeira vez ou num disco lento.
- **Sem atalhos nem desinstalação.** É só o arquivo: não aparece no Menu
  Iniciar nem em Configurações > Aplicativos.

As configurações continuam em %APPDATA%\\FileMorph — não ao lado do .exe —,
então usar o portátil e o instalado na mesma máquina dá as mesmas
preferências, e o portátil funciona de uma pasta sem permissão de escrita.

Metadados, ícone, recursos e exclusões são os mesmos da versão instalada
(`installer/pyinstaller_comum.py`).
"""

import sys
from pathlib import Path

RAIZ = Path(SPECPATH).resolve()
sys.path.insert(0, str(RAIZ / "installer"))

import pyinstaller_comum as comum  # noqa: E402

META = comum.ler_metadados(RAIZ)

a = Analysis(
    ["main.py"],
    pathex=[str(RAIZ)],
    binaries=[],
    datas=comum.dados(RAIZ),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=comum.EXCLUIDOS,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f"{META['nome']}-{META['versao']}-portable",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # Sem UPX pelo mesmo motivo da versão instalada: as DLLs do Qt quebram
    # ou disparam antivírus.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(RAIZ / "assets" / "icons" / "filemorph.ico"),
    version=comum.informacoes_de_versao(META),
)
