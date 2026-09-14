"""
Widget de progresso global.

Mostra a barra de progresso agregada, o arquivo atual sendo
processado e o botão de cancelar. Fica oculto quando não há
processamento em andamento.

A barra não avança só de arquivo em arquivo: ela também considera o
quanto já foi feito *dentro* das tarefas em andamento (a página 12 de
40 de um PDF, por exemplo). Quem calcula isso é o acompanhamento do
lote (`app/core/batch.py`) — aqui só se exibe o número recebido.

O bloco inteiro mora em um cartão (`QFrame#progressCard`), da mesma
família dos cards de arquivo: enquanto ele existe, é o que está
acontecendo no aplicativo, e três controles soltos sobre o fundo não
diziam isso. O percentual, que antes não aparecia em lugar nenhum
(a barra é sem texto de propósito, para poder ser fina), ganhou o
canto direito da primeira linha.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


class ProgressWidget(QFrame):
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("progressCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 13, 16, 14)
        outer.setSpacing(9)

        # Primeira linha: o que está acontecendo, e o quanto já foi.
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self._status_label = QLabel("Convertendo arquivos...")
        self._status_label.setObjectName("progressStatus")
        self._percent_label = QLabel("0%")
        self._percent_label.setObjectName("progressPercent")
        top_row.addWidget(self._status_label)
        top_row.addStretch()
        top_row.addWidget(self._percent_label)

        self._current_file_label = QLabel("")
        self._current_file_label.setObjectName("hintLabel")

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        # O percentual ja esta ao lado do rotulo de status; dentro da
        # barra ele so obrigaria a barra a ser alta o bastante para o texto.
        self._progress_bar.setTextVisible(False)

        self._cancel_button = QPushButton("Cancelar")
        self._cancel_button.setObjectName("cancelButton")
        self._cancel_button.clicked.connect(self.cancel_requested)

        bottom_row.addWidget(self._progress_bar, 1)
        bottom_row.addWidget(self._cancel_button)

        outer.addLayout(top_row)
        outer.addLayout(bottom_row)
        outer.addWidget(self._current_file_label)

        self.hide()

    def start(self, total_files: int) -> None:
        self._total = max(total_files, 1)
        self._progress_bar.setValue(0)
        self._status_label.setText(f"0 de {self._total} arquivos")
        self._percent_label.setText("0%")
        self._current_file_label.setText("")
        self.show()

    def update_current_file(self, filename: str) -> None:
        self._current_file_label.setText(f"Processando: {filename}")

    def report(self, completed: int, percent: int) -> None:
        """`completed` são os arquivos já finalizados (para o texto) e
        `percent` é o andamento real do lote, já incluindo o que foi
        feito dentro das tarefas em curso."""
        limitado = max(0, min(100, percent))
        self._progress_bar.setValue(limitado)
        self._percent_label.setText(f"{limitado}%")
        self._status_label.setText(f"{completed} de {self._total} arquivos")

    def finish(self) -> None:
        self.hide()
        self._current_file_label.setText("")
