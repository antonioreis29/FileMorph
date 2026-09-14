"""
Configuração comum da suíte de testes.

**A aplicação Qt da suíte.** Um processo só pode ter uma aplicação Qt, e o
tipo dela importa: os testes de janela precisam de uma `QApplication`, e
uma `QCoreApplication` criada antes — que é o que o teste da fila de
tarefas cria quando não encontra nenhuma — impediria isso pelo resto da
execução. Com a ordem alfabética dos arquivos isso nunca acontecia, mas
bastava rodar os arquivos em outra ordem para os testes de janela serem
pulados. Por isso a aplicação é criada aqui, antes de qualquer teste, já do
tipo que serve a todos. A plataforma "offscreen" faz as janelas existirem
sem aparecer na tela de quem roda a suíte.

**Nada de FFmpeg nem LibreOffice de verdade.** O resultado da suíte não pode
mudar conforme o que está instalado na máquina que a roda. A fixture
`_no_real_external_programs` faz a detecção dos dois programas responder
"ausente" em todo teste; quem precisa de um deles usa os programas de
mentira (`fake_ffmpeg.py`, `fake_soffice.py`) de forma explícita.

**Nem as configurações e os temporários de quem usa a máquina.** A pasta de
dados do aplicativo (configurações e logs) é trocada por uma pasta
descartável antes de qualquer módulo do FileMorph ser importado, e o
gerenciador de temporários passa a trabalhar dentro da pasta temporária
da própria suíte. Um tema escuro escolhido por quem roda os testes não
muda o resultado deles, e um FileMorph aberto na mesma máquina não é
incomodado.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Antes de importar o aplicativo: a instância global das configurações lê o
# arquivo no momento em que o módulo é carregado.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="filemorph-testes-")
os.environ["FILEMORPH_DATA_DIR"] = _TEST_DATA_DIR

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover — sem PySide6, os testes de Qt se pulam sozinhos
    QApplication = None  # type: ignore[assignment,misc]

if QApplication is not None and QApplication.instance() is None:
    # Guardada em variável de módulo: sem uma referência viva, o Python
    # poderia destruir a aplicação no meio da suíte.
    _QT_APPLICATION = QApplication([])


@pytest.fixture(scope="session", autouse=True)
def _isolated_app_folders(tmp_path_factory: pytest.TempPathFactory):
    """Temporários da suíte numa pasta da própria suíte, apagados no fim,
    junto com a pasta de dados descartável."""
    from app.utils.temp_manager import temp_manager

    temp_manager.cleanup_own()
    # A instância global é reconfigurada no lugar, e não substituída: os
    # módulos que já a importaram continuam apontando para ela.
    temp_manager.__init__(tmp_path_factory.mktemp("filemorph-temp"))
    yield
    temp_manager.cleanup_own()
    import logging

    for handler in list(logging.getLogger("filemorph").handlers):
        handler.close()
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _no_real_external_programs(monkeypatch: pytest.MonkeyPatch) -> None:
    """A detecção do FFmpeg e do LibreOffice responde "ausente" em todo teste.

    Os gerenciadores globais esquecem o que já tinham detectado, para que
    nenhum resultado guardado de fora do teste vaze para dentro dele. Os
    gerenciadores criados pelos testes com um programa de mentira
    (`executable=[...]`) não passam pela detecção e continuam funcionando.
    """
    from app.utils import ffmpeg_manager as ffmpeg_module
    from app.utils import libreoffice_manager as libreoffice_module

    monkeypatch.setattr(
        ffmpeg_module,
        "detect_ffmpeg",
        lambda **_options: ffmpeg_module.FFmpegStatus(False, None, None),
    )
    monkeypatch.setattr(
        libreoffice_module,
        "detect_libreoffice",
        lambda *_args, **_options: libreoffice_module.LibreOfficeStatus(False, None, None),
    )
    for manager, attributes in (
        (ffmpeg_module.ffmpeg_manager, ("_status", "_encoders")),
        (libreoffice_module.libreoffice_manager, ("_status",)),
    ):
        for attribute in attributes:
            monkeypatch.setattr(manager, attribute, None)
