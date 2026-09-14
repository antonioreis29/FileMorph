"""
Lista de arquivos adicionados, exibidos como cards.

Cada card mostra ícone, nome, extensão, tamanho, status e um botão de
remover. `FileListWidget` gerencia a coleção de cards e expõe sinais
para quando um arquivo é removido ou quando a lista muda (para que a
janela principal possa recalcular o seletor de formato e habilitar/
desabilitar o botão principal).

O card tem duas linhas: o nome em cima e, embaixo, o tipo e o tamanho.
Antes essas duas informações só existiam no tooltip, o que equivale a
não existirem para quem não passa o mouse — e a linha única deixava o
nome disputar espaço com o status. O nome é **encurtado no meio**
(`ElidedLabel`) em vez de esticar o card: começo e fim de um nome longo
são justamente as partes que identificam o arquivo.
"""

from __future__ import annotations

from dataclasses import dataclass

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

# A situação de cada arquivo é definida no núcleo, junto do acompanhamento
# do lote que a altera; aqui só se decide como ela aparece.
from app.core.batch import FileStatus
from app.ui.file_icons import ICON_SIZE, fallback_emoji, icon_pixmap
from app.utils.file_utils import get_extension, get_file_size_display, get_filename

__all__ = ["ElidedLabel", "FileCard", "FileEntry", "FileListWidget", "FileStatus"]

_STATUS_LABELS = {
    FileStatus.WAITING.value: "aguardando",
    FileStatus.PROCESSING.value: "processando",
    FileStatus.DONE.value: "concluído",
    FileStatus.ERROR.value: "erro",
    FileStatus.CANCELLED.value: "cancelado",
}


@dataclass
class FileEntry:
    path: str
    status: FileStatus = FileStatus.WAITING
    error_message: str | None = None


class ElidedLabel(QLabel):
    """Um QLabel que encurta o próprio texto com "…" quando não cabe.

    O corte é recalculado a cada mudança de largura e aplicado com
    `super().setText`, de modo que quem pinta continua sendo o QLabel
    de sempre — e, com isso, a cor e a fonte continuam vindo do QSS.
    Pintar o texto à mão em `paintEvent` custaria essa ligação.

    A política horizontal é `Ignored` de propósito: sem isso o rótulo
    pediria ao layout a largura do texto inteiro, que é exatamente o
    que se quer evitar — o card ficaria largo em vez de o nome ficar
    curto.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802 — nome do Qt
        self._full_text = text
        self._apply_elision()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802 — nome do Qt
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        largura = max(self.width() - 2, 32)
        super().setText(
            self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideMiddle, largura)
        )


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
        outer.setContentsMargins(14, 10, 10, 10)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(12)

        # O ícone gráfico é o caminho normal; o emoji só entra se a
        # arte não estiver instalada (veja app/ui/file_icons.py).
        self._icon_label = QLabel()
        self._icon_label.setObjectName("cardIcon")
        pixmap = icon_pixmap(entry.path)
        if pixmap is not None:
            self._icon_label.setPixmap(pixmap)
            # Sem setScaledContents: o pixmap ja vem no tamanho certo,
            # e estica-lo achataria a folha.
            self._icon_label.setFixedHeight(ICON_SIZE)
        else:
            self._icon_label.setText(fallback_emoji(entry.path))
        self._icon_label.setAccessibleName(f"Arquivo {get_extension(entry.path).upper()}")

        # As duas linhas de texto do card, empilhadas: o nome manda, o
        # tipo e o tamanho ficam abaixo, em tom secundário.
        text_column = QVBoxLayout()
        text_column.setSpacing(1)
        text_column.setContentsMargins(0, 0, 0, 0)

        self._name_label = ElidedLabel(get_filename(entry.path))
        self._name_label.setObjectName("cardName")

        ext = get_extension(entry.path).upper()
        self._meta_label = QLabel(f"{ext} • {get_file_size_display(entry.path)}")
        self._meta_label.setObjectName("cardMeta")

        text_column.addWidget(self._name_label)
        text_column.addWidget(self._meta_label)

        self._status_label = QLabel(_STATUS_LABELS[entry.status.value])
        self._status_label.setObjectName("cardStatus")
        self._status_label.setProperty("status", entry.status.value)

        self._remove_button = QPushButton("×")
        self._remove_button.setObjectName("cardRemove")
        self._remove_button.setFixedSize(26, 26)
        self._remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_button.setToolTip("Remover da lista")
        self._remove_button.clicked.connect(lambda: self.remove_requested.emit(entry.path))

        row.addWidget(self._icon_label)
        row.addLayout(text_column, 1)
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

        # O caminho completo continua no tooltip: é a única informação
        # do card que não tem como caber na linha em nenhum tamanho.
        self.setToolTip(entry.path)

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
        # A barra horizontal nunca deve aparecer: o card se adapta à
        # largura (o nome encurta), então uma barra horizontal só
        # poderia ser sintoma de um card que não soube encolher.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
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

    def count(self) -> int:
        return len(self._cards)

    def set_status(self, path: str, status: FileStatus, error_message: str | None = None) -> None:
        card = self._cards.get(path)
        if card is not None:
            card.set_status(status, error_message)

    def reorder(self, ordered_paths: list[str]) -> None:
        """Reordena os cards conforme a lista fornecida: a ordem da lista
        determina a ordem do arquivo final na junção."""
        for path in ordered_paths:
            card = self._cards.get(path)
            if card is not None:
                self._layout.removeWidget(card)
                self._layout.insertWidget(self._layout.count() - 1, card)
