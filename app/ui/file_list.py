"""
Lista de arquivos adicionados, exibidos como cards (item 9 do briefing).

Cada card mostra ícone, nome, extensão, tamanho, status e um botão de
remover. `FileListWidget` gerencia a coleção de cards e expõe sinais
para quando um arquivo é removido ou quando a lista muda (para que a
janela principal possa recalcular o seletor de formato e habilitar/
desabilitar o botão principal).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.file_validator import get_file_category
from app.utils.file_utils import get_extension, get_file_size_display, get_filename

_CATEGORY_ICONS = {
    "imagem": "🖼",
    "pdf": "📕",
    "documento": "📄",
    "audio": "🎵",
    "video": "🎬",
    "planilha": "📊",
}

_STATUS_LABELS = {
    "waiting": "aguardando",
    "processing": "processando",
    "done": "concluído",
    "error": "erro",
    "cancelled": "cancelado",
}


class FileStatus(str, Enum):
    WAITING = "waiting"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class FileEntry:
    path: str
    status: FileStatus = FileStatus.WAITING
    error_message: str | None = None


class FileCard(QFrame):
    """Card individual representando um arquivo na lista."""

    remove_requested = Signal(str)  # path

    def __init__(self, entry: FileEntry, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("fileCard")
        self.entry = entry
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(Qt.GlobalColor.gray)
        self.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)

        category = get_file_category(entry.path)
        icon = _CATEGORY_ICONS.get(category or "", "📁")
        self._icon_label = QLabel(icon)
        self._icon_label.setStyleSheet("font-size: 22px;")

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        self._name_label = QLabel(get_filename(entry.path))
        self._name_label.setStyleSheet("font-weight: 600;")
        ext = get_extension(entry.path).upper()
        size = get_file_size_display(entry.path)
        self._meta_label = QLabel(f"{ext} • {size} • {_STATUS_LABELS[entry.status.value]}")
        self._meta_label.setObjectName("hintLabel")
        text_layout.addWidget(self._name_label)
        text_layout.addWidget(self._meta_label)

        self._remove_button = QPushButton("×")
        self._remove_button.setFixedSize(28, 28)
        self._remove_button.clicked.connect(lambda: self.remove_requested.emit(entry.path))

        layout.addWidget(self._icon_label)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self._remove_button)

    def set_status(self, status: FileStatus, error_message: str | None = None) -> None:
        self.entry.status = status
        self.entry.error_message = error_message
        ext = get_extension(self.entry.path).upper()
        size = get_file_size_display(self.entry.path)
        text = f"{ext} • {size} • {_STATUS_LABELS[status.value]}"
        if status == FileStatus.ERROR and error_message:
            text += f" — {error_message}"
        self._meta_label.setText(text)


class FileListWidget(QScrollArea):
    """Container com rolagem para os FileCards, um por arquivo adicionado."""

    files_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setSpacing(8)
        self._layout.addStretch()
        self.setWidget(self._container)

        self._cards: dict[str, FileCard] = {}

    def add_files(self, paths: list[str]) -> list[str]:
        """Adiciona arquivos novos (ignora duplicados). Retorna a lista de
        caminhos efetivamente adicionados."""
        added: list[str] = []
        for path in paths:
            if path in self._cards:
                continue
            entry = FileEntry(path=path)
            card = FileCard(entry)
            card.remove_requested.connect(self.remove_file)
            # Insere antes do stretch final.
            self._layout.insertWidget(self._layout.count() - 1, card)
            self._cards[path] = card
            added.append(path)
        if added:
            self.files_changed.emit()
        return added

    def remove_file(self, path: str) -> None:
        card = self._cards.pop(path, None)
        if card is not None:
            self._layout.removeWidget(card)
            card.deleteLater()
            self.files_changed.emit()

    def clear(self) -> None:
        for path in list(self._cards.keys()):
            self.remove_file(path)

    def get_paths(self) -> list[str]:
        return list(self._cards.keys())

    def is_empty(self) -> bool:
        return len(self._cards) == 0

    def set_status(self, path: str, status: FileStatus, error_message: str | None = None) -> None:
        card = self._cards.get(path)
        if card is not None:
            card.set_status(status, error_message)

    def reorder(self, ordered_paths: list[str]) -> None:
        """Reordena os cards conforme a lista fornecida (item 12: a
        ordem determina a ordem do arquivo final na junção)."""
        for path in ordered_paths:
            card = self._cards.get(path)
            if card is not None:
                self._layout.removeWidget(card)
                self._layout.insertWidget(self._layout.count() - 1, card)
