"""
Ponto de entrada do FileMorph.

Responsável apenas por inicializar logging, criar a QApplication e
mostrar a janela principal. Nenhuma lógica de negócio mora aqui
(item 37: "não colocar toda a lógica em main.py").
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.converters import register_builtin_converters
from app.mergers import register_builtin_mergers
from app.utils.logger import setup_logging
from app.utils.temp_manager import temp_manager


def main() -> int:
    setup_logging()

    # Remove qualquer resto de arquivos temporários de uma execução
    # anterior que tenha sido interrompida (item 24).
    temp_manager.cleanup_all()

    # Preenche a camada de compatibilidade com os conversores e mergers
    # realmente disponíveis nesta instalação. Precisa acontecer antes da
    # janela ser construída, porque é isso que define quais formatos o
    # seletor vai oferecer e se o modo "Juntar" fica utilizável (item 14).
    register_builtin_converters()
    register_builtin_mergers()

    app = QApplication(sys.argv)
    app.setApplicationName("FileMorph")
    app.setOrganizationName("FileMorph")

    # Import tardio para garantir que a QApplication já exista antes de
    # qualquer widget ser construído.
    from app.ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
