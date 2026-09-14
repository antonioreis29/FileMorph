# -*- mode: python ; coding: utf-8 -*-
"""
Receita do PyInstaller para empacotar o FileMorph numa pasta (dist/FileMorph).

    pyinstaller FileMorph.spec --noconfirm

Ou, mais simples, use o `empacotar.ps1` na raiz do projeto, que chama
isto, verifica o executável e depois monta o instalador.

**Esta é a distribuição principal.** O `FileMorph.exe` dentro de
dist/FileMorph depende de todos os arquivos da pasta ao lado dele (o
Python, o Qt, as bibliotecas), e por isso não é um executável para ser
enviado sozinho: quem é enviado ao usuário é o instalador que o Inno Setup
monta com a pasta inteira, `dist/installer/FileMorph-<versão>-setup.exe`.

**Por que um .spec e não uma linha de comando.** As opções de
empacotamento do FileMorph passaram de meia dúzia — ícone, recursos,
metadados de versão, módulos a excluir — e uma linha de comando com tudo
isso é longa demais para ser digitada certo duas vezes. O .spec é a mesma
configuração, versionada junto do projeto. O que ele tem em comum com a
receita do executável portátil mora em `installer/pyinstaller_comum.py`.

**Por que "onedir" e não "onefile".** O modo de arquivo único descompacta
o aplicativo inteiro numa pasta temporária a cada abertura — com o PySide6
isso são centenas de MB e vários segundos de espera antes da janela
aparecer. Instalada, a pasta abre na hora. O arquivo único existe como
opção à parte (`FileMorph-portable.spec`), para quem não pode instalar.
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
    [],
    exclude_binaries=True,
    name=META["nome"],
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=False é o que faz o aplicativo abrir sem janela de terminal.
    # Nele sys.stdout e sys.stderr não existem — ver app/utils/logger.py.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(RAIZ / "assets" / "icons" / "filemorph.ico"),
    version=comum.informacoes_de_versao(META),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    # O UPX comprime as DLLs, mas as do Qt costumam quebrar ou fazer
    # antivírus reclamarem — e o ganho de tamanho some assim que o
    # Inno Setup comprime tudo de novo.
    upx=False,
    upx_exclude=[],
    name=META["nome"],
)
