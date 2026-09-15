"""
Identidade do FileMorph perante o Windows e ícone do aplicativo.

A barra de tarefas agrupa as janelas pelo AppUserModelID do processo. Sem
um explícito, o Windows usa o do executável que abriu a janela — e rodando
pelo código-fonte esse executável é o python.exe, que aparece com o ícone
do Python. Declarar o ID antes de criar qualquer janela faz o FileMorph ser
um aplicativo próprio na barra, com o ícone do Ditto.
"""

from __future__ import annotations

import sys
from typing import Any

from app.utils.logger import get_logger
from app.version import APP_USER_MODEL_ID

logger = get_logger("utils.app_identity")


def set_windows_app_user_model_id(shell32: Any = None) -> bool:
    """Declara o AppUserModelID do FileMorph para este processo.

    Precisa rodar antes de a primeira janela existir. Fora do Windows não
    faz nada. Uma falha não impede o aplicativo de abrir: só volta o ícone
    agrupado de antes, e isso vai para o log. `shell32` existe para os
    testes. Devolve True se o Windows aceitou.
    """
    if shell32 is None:
        if sys.platform != "win32":
            return False
        import ctypes

        shell32 = ctypes.windll.shell32
    try:
        resultado = shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError) as exc:
        logger.warning("Não foi possível declarar o AppUserModelID: %s", exc)
        return False
    # HRESULT: 0 (S_OK) é sucesso.
    if resultado != 0:
        logger.warning("O Windows recusou o AppUserModelID (HRESULT %s).", resultado)
        return False
    return True


def apply_application_icon(app: Any) -> bool:
    """Põe o ícone do FileMorph na aplicação inteira: janela principal,
    diálogos e barra de tarefas. Sem o arquivo, o Qt usa o padrão."""
    from PySide6.QtGui import QIcon

    from app.utils.resources import ICON_PATH, get_asset

    icone = get_asset(*ICON_PATH)
    if icone is None:
        logger.warning("Ícone do aplicativo não encontrado; usando o padrão.")
        return False
    app.setWindowIcon(QIcon(str(icone)))
    return True
