# -*- mode: python ; coding: utf-8 -*-
"""
Receita do PyInstaller para empacotar o FileMorph num executável.

    pyinstaller FileMorph.spec --noconfirm

Ou, mais simples, use o `empacotar.ps1` na raiz do projeto, que chama
isto e depois monta o instalador.

**Por que um .spec e não uma linha de comando.** As opções de
empacotamento do FileMorph passaram de meia dúzia — ícone, pasta de
recursos, metadados de versão, módulos a excluir — e uma linha de
comando com tudo isso é longa demais para ser digitada certo duas
vezes. O .spec é a mesma configuração, versionada junto do projeto.

**Por que "onedir" e não "onefile".** O modo de arquivo único parece
mais elegante, mas descompacta o aplicativo inteiro numa pasta
temporária a cada abertura — com o PySide6 isso são centenas de MB e
vários segundos de espera antes da janela aparecer. Como o resultado
vai ser embrulhado num setup.exe pelo Inno Setup de qualquer forma, o
usuário nunca vê a pasta, e a abertura fica instantânea. O arquivo
único só faria sentido para distribuir o .exe cru, sem instalador.
"""

import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

RAIZ = Path(SPECPATH).resolve()


def ler_metadados() -> dict[str, str]:
    """Lê nome, versão e autor de app/version.py.

    Por expressão regular, e não importando o módulo: o `app` importa
    coisas que não devem ser carregadas durante a análise do
    PyInstaller, e ler três constantes não justifica esse risco.
    """
    texto = (RAIZ / "app" / "version.py").read_text(encoding="utf-8")

    def constante(nome: str, padrao: str) -> str:
        achado = re.search(rf'^{nome}\s*=\s*"([^"]*)"', texto, re.M)
        return achado.group(1) if achado else padrao

    return {
        "versao": constante("__version__", "0.0.0"),
        "nome": constante("APP_NAME", "FileMorph"),
        "autor": constante("APP_PUBLISHER", ""),
    }


META = ler_metadados()

# O Windows exige a versão como quatro números no recurso do
# executável, enquanto o projeto usa três. O quarto é o "build" e fica
# em zero, que é a convenção para quem não numera builds.
_partes = [int(p) for p in META["versao"].split(".")]
VERSAO_WIN = tuple(_partes + [0] * (4 - len(_partes)))[:4]

# Estes campos são o que aparece em Propriedades > Detalhes do .exe, e
# também o que o Windows mostra no aviso de "editor desconhecido" ao
# abrir um programa sem assinatura digital. Preenchê-los não substitui
# uma assinatura, mas deixa o aviso menos anônimo.
VERSION_INFO = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=VERSAO_WIN,
        prodvers=VERSAO_WIN,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
    ),
    kids=[
        StringFileInfo([
            StringTable(
                # 0409 = inglês dos EUA, 04B0 = Unicode. É a combinação
                # que o Windows procura primeiro; um bloco só em
                # português seria ignorado por muitas ferramentas.
                "040904B0",
                [
                    StringStruct("CompanyName", META["autor"]),
                    StringStruct("FileDescription", "Converta, transforme e junte arquivos localmente"),
                    StringStruct("FileVersion", META["versao"]),
                    StringStruct("InternalName", META["nome"]),
                    StringStruct("LegalCopyright", f"© {META['autor']}"),
                    StringStruct("OriginalFilename", f"{META['nome']}.exe"),
                    StringStruct("ProductName", META["nome"]),
                    StringStruct("ProductVersion", META["versao"]),
                ],
            )
        ]),
        VarFileInfo([VarStruct("Translation", [0x0409, 0x04B0])]),
    ],
)

# A pasta assets inteira vai junto: os ícones de tipo de arquivo, o
# .ico do aplicativo e o mascote. O `app/utils/resources.py` já sabe
# procurá-la em sys._MEIPASS quando empacotado, então nada muda no
# código por causa disto.
DADOS = [(str(RAIZ / "assets"), "assets")]

# Bibliotecas que existem no requirements.txt mas não têm nada a fazer
# dentro do executável do usuário final. Sem excluí-las, o pytest e o
# próprio PyInstaller entrariam no pacote e o engordariam à toa.
EXCLUIDOS = [
    "pytest",
    "_pytest",
    "PyInstaller",
    "setuptools",
    "pip",
    # Módulos pesados do Qt que o FileMorph não usa. O PySide6 traz o
    # QtWebEngine com um Chromium inteiro dentro; deixá-lo entrar
    # dobraria o tamanho do instalador sem motivo.
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.QtMultimedia",
]

a = Analysis(
    ["main.py"],
    pathex=[str(RAIZ)],
    binaries=[],
    datas=DADOS,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUIDOS,
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
    # console=False é o que faz o aplicativo abrir sem janela de
    # terminal. É o equivalente empacotado do pythonw.exe que o
    # install.ps1 usa na instalação a partir do código-fonte.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(RAIZ / "assets" / "icons" / "filemorph.ico"),
    version=VERSION_INFO,
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
