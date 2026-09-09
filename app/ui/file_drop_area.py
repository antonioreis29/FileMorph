"""
Área de arrastar-e-soltar (item 8 do briefing).

Aceita múltiplos arquivos, destaca-se visualmente durante o arraste,
valida extensões e comunica arquivos válidos/inválidos via sinais —
quem decide o que fazer com eles é o widget pai (main_window.py).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.core.file_validator import validate_paths


class FileDropArea(QFrame):
    """Área central de drop. Também clicável para abrir um seletor de
    arquivos tradicional, para quem preferir não arrastar."""

    files_dropped = Signal(list, list)  # (validos, invalidos)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(180)
        self.setProperty("dragActive", False)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        self._icon_label = QLabel("📄")
        self._icon_label.setStyleSheet("font-size: 40px;")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._main_label = QLabel("Arraste seus arquivos aqui")
        self._main_label.setObjectName("titleLabel")
        self._main_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        self._hint_label = QLabel("ou clique para selecionar")
        self._hint_label.setObjectName("hintLabel")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        self._browse_button = QPushButton("Selecionar arquivos")
        self._browse_button.clicked.connect(self._open_file_dialog)

        layout.addStretch()
        layout.addWidget(self._icon_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._main_label)
        layout.addWidget(self._hint_label)
        layout.addSpacing(8)
        layout.addWidget(self._browse_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()

    # --- Drag and drop -----------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self._set_drag_active(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drag_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drag_active(False)
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            valid, invalid = validate_paths(paths)
            self.files_dropped.emit(valid, invalid)
        event.acceptProposedAction()

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    # --- Seleção manual -------------------------------------------------

    def _open_file_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Selecionar arquivos")
        if paths:
            valid, invalid = validate_paths(paths)
            self.files_dropped.emit(valid, invalid)
