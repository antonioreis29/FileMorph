"""
Ponto de entrada do FileMorph.

Responsável apenas por inicializar logging, preparar os temporários,
registrar as operações disponíveis, criar a QApplication e mostrar a
janela principal. Nenhuma lógica de negócio mora aqui.

`FileMorph.exe --smoke-test <relatorio.json>` roda a verificação rápida do
executável empacotado em vez de abrir a janela (ver `app/smoke_test.py`).
"""

from __future__ import annotations

import sys


def _log_uncaught_exceptions() -> None:
    """Leva ao log qualquer exceção que escape de um slot do Qt.

    No executável distribuído não há console: sem isto, um erro inesperado
    num clique sumiria sem deixar rastro nenhum para diagnóstico.
    """
    from app.utils.logger import get_logger

    logger = get_logger("main")
    previous_hook = sys.excepthook

    def hook(exc_type, exc_value, exc_traceback) -> None:
        logger.critical(
            "Exceção não tratada", exc_info=(exc_type, exc_value, exc_traceback)
        )
        if sys.stderr is not None:
            previous_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = hook


def main() -> int:
    if "--smoke-test" in sys.argv:
        from app.smoke_test import run_smoke_test

        return run_smoke_test(sys.argv)

    from PySide6.QtWidgets import QApplication

    from app.config.settings import settings_manager
    from app.converters import register_builtin_converters
    from app.mergers import register_builtin_mergers
    from app.organizers import register_builtin_organizers
    from app.utils.ffmpeg_manager import ffmpeg_manager
    from app.utils.logger import setup_logging
    from app.utils.temp_manager import temp_manager

    setup_logging()
    _log_uncaught_exceptions()

    # Remove o que sobrou de execuções anteriores que terminaram sem
    # limpar — só o que é comprovadamente abandonado: outra janela do
    # FileMorph aberta agora mantém os temporários dela.
    temp_manager.cleanup_orphans()

    # O FFmpeg escolhido nas configurações entra na procura antes de os
    # conversores perguntarem se ele existe.
    ffmpeg_manager.set_configured_path(settings_manager.settings.ffmpeg_path)

    # Preenche a camada de compatibilidade com os conversores, mergers e
    # organizadores de páginas realmente disponíveis nesta instalação.
    # Precisa acontecer antes da janela ser construída, porque é isso que
    # define quais formatos o seletor vai oferecer e se os modos "Juntar"
    # e "Organizar" ficam utilizáveis.
    register_builtin_converters()
    register_builtin_mergers()
    register_builtin_organizers()

    from app.utils.app_identity import apply_application_icon, set_windows_app_user_model_id

    # Antes de qualquer janela: é o que tira o FileMorph do grupo do
    # python.exe na barra de tarefas e mostra o ícone do Ditto.
    set_windows_app_user_model_id()

    app = QApplication(sys.argv)
    app.setApplicationName("FileMorph")
    app.setOrganizationName("FileMorph")
    apply_application_icon(app)
    # Os temporários desta execução saem junto com ela.
    app.aboutToQuit.connect(temp_manager.cleanup_own)

    # Import tardio para garantir que a QApplication já exista antes de
    # qualquer widget ser construído.
    from app.ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    try:
        return app.exec()
    finally:
        temp_manager.cleanup_own()


if __name__ == "__main__":
    sys.exit(main())
