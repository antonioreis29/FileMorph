"""Identidade do FileMorph na barra de tarefas do Windows e ícone do app."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from app.utils import app_identity
from app.version import APP_USER_MODEL_ID

RAIZ = Path(__file__).resolve().parent.parent


class _FakeShell32:
    def __init__(self, resultado=0, erro: Exception | None = None) -> None:
        self.resultado = resultado
        self.erro = erro
        self.chamadas: list[str] = []

    def SetCurrentProcessExplicitAppUserModelID(self, app_id: str) -> int:  # noqa: N802
        self.chamadas.append(app_id)
        if self.erro is not None:
            raise self.erro
        return self.resultado


def test_declara_o_app_user_model_id_do_filemorph() -> None:
    shell32 = _FakeShell32()
    assert app_identity.set_windows_app_user_model_id(shell32) is True
    assert shell32.chamadas == [APP_USER_MODEL_ID]


@pytest.mark.parametrize(
    "shell32",
    [_FakeShell32(resultado=-2147024809), _FakeShell32(erro=OSError("negado"))],
    ids=["hresult-de-erro", "excecao"],
)
def test_falha_do_windows_nao_impede_o_app_de_abrir(shell32) -> None:
    assert app_identity.set_windows_app_user_model_id(shell32) is False


def test_fora_do_windows_nao_faz_nada(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert app_identity.set_windows_app_user_model_id() is False


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="só no Windows")
def test_windows_aceita_o_id_de_verdade() -> None:
    # Roda em um subprocesso para não mudar a identidade do próprio pytest.
    import subprocess

    codigo = (
        "import sys; from app.utils.app_identity import set_windows_app_user_model_id as f;"
        "sys.exit(0 if f() else 1)"
    )
    resultado = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, timeout=60)
    assert resultado.returncode == 0


def test_instalador_usa_o_mesmo_id_nos_atalhos_do_app() -> None:
    iss = (RAIZ / "installer" / "FileMorph.iss").read_text(encoding="utf-8")
    definido = re.search(r'#define MyAppUserModelID "([^"]+)"', iss)
    assert definido is not None and definido.group(1) == APP_USER_MODEL_ID

    atalhos_do_app = [
        linha
        for linha in iss.splitlines()
        if linha.startswith("Name:") and "{#MyAppExeName}" in linha
    ]
    assert len(atalhos_do_app) == 2
    for linha in atalhos_do_app:
        assert 'AppUserModelID: "{#MyAppUserModelID}"' in linha


@pytest.fixture()
def qapp():
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        pytest.skip("O ícone da aplicação precisa de uma QApplication.")
    anterior = app.windowIcon()
    app.setWindowIcon(QIcon())
    yield app
    app.setWindowIcon(anterior)


def test_icone_do_aplicativo_e_aplicado(qapp) -> None:
    assert qapp.windowIcon().isNull()
    assert app_identity.apply_application_icon(qapp) is True
    assert not qapp.windowIcon().isNull()


def test_sem_arquivo_de_icone_nao_quebra(qapp, monkeypatch) -> None:
    import app.utils.resources as resources

    monkeypatch.setattr(resources, "get_asset", lambda *partes: None)
    assert app_identity.apply_application_icon(qapp) is False
    assert qapp.windowIcon().isNull()
