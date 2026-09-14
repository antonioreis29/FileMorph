"""
O que as duas receitas do PyInstaller têm em comum.

`FileMorph.spec` (a pasta que o instalador distribui) e
`FileMorph-portable.spec` (o executável único, opcional) precisam dos mesmos
metadados de versão, dos mesmos recursos e das mesmas exclusões. Escrito duas
vezes, cedo ou tarde um dos dois sairia com uma versão ou um recurso
diferente — por isso mora aqui, e as receitas só dizem o que as distingue.

Este arquivo é lido pelo PyInstaller durante o empacotamento; ele não faz
parte do aplicativo.
"""

from __future__ import annotations

import re
from pathlib import Path


def ler_metadados(raiz: Path) -> dict[str, str]:
    """Lê nome, versão e autor de app/version.py.

    Por expressão regular, e não importando o módulo: o `app` importa
    coisas que não devem ser carregadas durante a análise do
    PyInstaller, e ler três constantes não justifica esse risco.
    """
    texto = (raiz / "app" / "version.py").read_text(encoding="utf-8")

    def constante(nome: str, padrao: str) -> str:
        achado = re.search(rf'^{nome}\s*=\s*"([^"]*)"', texto, re.M)
        return achado.group(1) if achado else padrao

    return {
        "versao": constante("__version__", "0.0.0"),
        "nome": constante("APP_NAME", "FileMorph"),
        "autor": constante("APP_PUBLISHER", ""),
    }


def informacoes_de_versao(meta: dict[str, str]):
    """O recurso de versão do .exe (Propriedades > Detalhes).

    Estes campos também são o que o Windows mostra no aviso de "editor
    desconhecido" ao abrir um programa sem assinatura digital. Preenchê-los
    não substitui uma assinatura, mas deixa o aviso menos anônimo.
    """
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    # O Windows exige a versão como quatro números no recurso do
    # executável, enquanto o projeto usa três. O quarto é o "build" e fica
    # em zero, que é a convenção para quem não numera builds.
    partes = [int(p) for p in meta["versao"].split(".")]
    versao_win = tuple(partes + [0] * (4 - len(partes)))[:4]

    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=versao_win,
            prodvers=versao_win,
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
                        StringStruct("CompanyName", meta["autor"]),
                        StringStruct("FileDescription", "Converta, transforme e junte arquivos localmente"),
                        StringStruct("FileVersion", meta["versao"]),
                        StringStruct("InternalName", meta["nome"]),
                        StringStruct("LegalCopyright", f"© {meta['autor']}"),
                        StringStruct("OriginalFilename", f"{meta['nome']}.exe"),
                        StringStruct("ProductName", meta["nome"]),
                        StringStruct("ProductVersion", meta["versao"]),
                    ],
                )
            ]),
            VarFileInfo([VarStruct("Translation", [0x0409, 0x04B0])]),
        ],
    )


# Arquivos do FFmpeg que acompanham o aplicativo quando estão em
# vendor/ffmpeg. O executável sozinho não basta: sem a licença junto, a
# receita recusa copiá-lo (ver `arquivos_do_ffmpeg`).
_FFMPEG_PROGRAMAS = ("ffmpeg.exe", "ffprobe.exe")
_FFMPEG_LICENCAS = ("LICENSE*", "COPYING*", "README*", "LEIA-ME-BUILD*")


def arquivos_do_ffmpeg(raiz: Path) -> list[tuple[str, str]]:
    """Os arquivos de vendor/ffmpeg a copiar para o pacote, ou nenhum.

    O build funciona sem a pasta — áudio e vídeo só ficam dependendo de um
    FFmpeg instalado na máquina do usuário. Com a pasta, o FFmpeg só entra
    se a licença do build escolhido estiver junto dele: redistribuir um
    binário sem os termos dele não é uma opção.
    """
    pasta = raiz / "vendor" / "ffmpeg"
    programas = [pasta / nome for nome in _FFMPEG_PROGRAMAS if (pasta / nome).is_file()]
    if not programas:
        print("[FileMorph] vendor/ffmpeg sem ffmpeg.exe: o pacote sai sem FFmpeg.")
        return []
    licencas = sorted({p for padrao in _FFMPEG_LICENCAS for p in pasta.glob(padrao) if p.is_file()})
    if not licencas:
        raise SystemExit(
            "[FileMorph] vendor/ffmpeg tem o FFmpeg, mas não tem o arquivo de licença "
            "do build (LICENSE, COPYING...). Coloque a licença junto antes de "
            "empacotar — ver vendor/ffmpeg/LEIA-ME.md."
        )
    print(f"[FileMorph] FFmpeg incluído: {', '.join(p.name for p in programas + licencas)}")
    return [(str(p), "vendor/ffmpeg") for p in programas + licencas]


def dados(raiz: Path) -> list[tuple[str, str]]:
    """Recursos que o aplicativo lê do disco em tempo de execução.

    - `assets`: os ícones, o .ico e o mascote. O `app/utils/resources.py` já
      sabe procurá-los em sys._MEIPASS quando empacotado.
    - `app/ui/filemorph.qss`: o modelo da folha de estilo, lido ao lado de
      `app/ui/styles.py` — sem ele a janela não abre.
    - O FFmpeg de vendor/ffmpeg, quando presente e acompanhado da licença.
    """
    return [
        (str(raiz / "assets"), "assets"),
        (str(raiz / "app" / "ui" / "filemorph.qss"), "app/ui"),
        *arquivos_do_ffmpeg(raiz),
    ]


# Bibliotecas que não têm nada a fazer dentro do executável do usuário
# final. O pytest e o próprio PyInstaller poderiam entrar no pacote por
# tabela e engordá-lo à toa.
EXCLUIDOS = [
    "pytest",
    "_pytest",
    "PyInstaller",
    "setuptools",
    "pip",
    # O Tk não é usado (a interface é Qt), e o Pillow o puxaria junto com
    # uma instalação inteira do Tcl.
    "tkinter",
    "_tkinter",
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
