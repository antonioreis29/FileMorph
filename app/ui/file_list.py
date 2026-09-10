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

        # Sem sombra: a antiga era cinza fixo, o que no tema escuro
        # virava um halo sujo em volta do card. A borda do QSS ja separa.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(13, 8, 8, 8)
        outer.setSpacing(3)

        row = QHBoxLayout()
        row.setSpacing(10)

        category = get_file_category(entry.path)
        icon = _CATEGORY_ICONS.get(category or "", "📁")
        self._icon_label = QLabel(icon)
        self._icon_label.setObjectName("cardIcon")

        self._name_label = QLabel(get_filename(entry.path))
        self._name_label.setObjectName("cardName")

        self._status_label = QLabel(_STATUS_LABELS[entry.status.value])
        self._status_label.setObjectName("cardStatus")
        self._status_label.setProperty("status", entry.status.value)

        self._remove_button = QPushButton("×")
        self._remove_button.setObjectName("cardRemove")
        self._remove_button.setFixedSize(24, 24)
        self._remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_button.clicked.connect(lambda: self.remove_requested.emit(entry.path))

        row.addWidget(self._icon_label)
        row.addWidget(self._name_label, 1)
        row.addWidget(self._status_label)
        row.addWidget(self._remove_button)
        outer.addLayout(row)

        # O motivo de um erro e longo demais para caber na linha; ele
        # ganha uma segunda linha, que so existe quando ha erro.
        self._error_label = QLabel()
        self._error_label.setObjectName("cardError")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        outer.addWidget(self._error_label)

        # Extensao e tamanho saem da linha para nao competir com o nome,
        # mas continuam a um passe de mouse de distancia.
        ext = get_extension(entry.path).upper()
        self.setToolTip(f"{ext} • {get_file_size_display(entry.path)}\n{entry.path}")

    def set_status(self, status: FileStatus, error_message: str | None = None) -> None:
        self.entry.status = status
        self.entry.error_message = error_message

        self._status_label.setText(_STATUS_LABELS[status.value])
        # A cor do status vem do QSS por propriedade dinamica, para que
        # todas as cores continuem morando na paleta. Trocar a
        # propriedade exige repolir o widget para o Qt reavaliar a regra.
        self._status_label.setProperty("status", status.value)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

        if status == FileStatus.ERROR and error_message:
            self._error_label.setText(error_message)
            self._error_label.show()
        else:
            self._error_label.hide()


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
