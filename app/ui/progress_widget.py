"""
Widget de progresso global (itens 16 e 17 do briefing).

Mostra a barra de progresso agregada, o arquivo atual sendo
processado e o botão de cancelar. Fica oculto quando não há
processamento em andamento.

Desde a Fase 5 a barra não avança só de arquivo em arquivo: ela também
considera o quanto já foi feito *dentro* das tarefas em andamento (a
página 12 de 40 de um PDF, por exemplo), o que quem calcula é a janela
principal — aqui só se exibe o número recebido.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget


class ProgressWidget(QWidget):
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._status_label = QLabel("Convertendo arquivos...")
        self._status_label.setObjectName("hintLabel")

        self._current_file_label = QLabel("")
        self._current_file_label.setObjectName("hintLabel")

        bottom_row = QHBoxLayout()
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(True)

        self._cancel_button = QPushButton("Cancelar")
        self._cancel_button.clicked.connect(self.cancel_requested)

        bottom_row.addWidget(self._progress_bar, 1)
        bottom_row.addWidget(self._cancel_button)

        outer.addWidget(self._status_label)
        outer.addLayout(bottom_row)
        outer.addWidget(self._current_file_label)

        self.hide()

    def start(self, total_files: int) -> None:
        self._total = max(total_files, 1)
        self._progress_bar.setValue(0)
        self._status_label.setText(f"0 de {self._total} arquivos")
        self._current_file_label.setText("")
        self.show()

    def update_current_file(self, filename: str) -> None:
        self._current_file_label.setText(f"Processando: {filename}")

    def report(self, completed: int, percent: int) -> None:
        """`completed` são os arquivos já finalizados (para o texto) e
        `percent` é o andamento real do lote, já incluindo o que foi
        feito dentro das tarefas em curso."""
        self._progress_bar.setValue(max(0, min(100, percent)))
        self._status_label.setText(f"{completed} de {self._total} arquivos")

    def finish(self) -> None:
        self.hide()
        self._current_file_label.setText("")
