"""
Área de arrastar-e-soltar.

Aceita múltiplos arquivos, destaca-se visualmente durante o arraste,
valida extensões e comunica arquivos válidos/inválidos via sinais —
quem decide o que fazer com eles é o widget pai (main_window.py).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from app.core.file_validator import validate_paths
from app.ui.mascot import MascotState, MascotWidget

# Altura do mascote dentro da área de arrastar, nos dois tamanhos da
# área (ver `set_compact`).
MASCOT_HEIGHT = 76
MASCOT_HEIGHT_COMPACT = 46

# Altura mínima da área de arrastar. Com a lista vazia ela é o assunto
# da janela e ocupa o espaço que sobrar; com arquivos na lista ela vira
# uma faixa, para que a lista fique com a altura.
DROP_HEIGHT = 180
DROP_HEIGHT_COMPACT = 108


class FileDropArea(QFrame):
    """Área central de drop. Também clicável para abrir um seletor de
    arquivos tradicional, para quem preferir não arrastar."""

    files_dropped = Signal(list, list)  # (validos, invalidos)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(DROP_HEIGHT)
        self.setProperty("dragActive", False)
        self._compact = False

        # A area inteira abre o seletor de arquivos, entao o cursor
        # precisa avisar que ela e clicavel - antes so o botao era, e o
        # texto "ou clique para selecionar" mentia sobre o resto dela.
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        self._layout = layout

        # O mascote recebe quem chega. Sem imagem, ele se esconde e o
        # texto sobe - a area continua funcionando igual.
        #
        # O widget tem largura fixa (precisa de folga para o mascote
        # pular e balancar sem ser cortado), e um QWidget de tamanho fixo
        # dentro de um layout vertical ficaria encostado a esquerda. A
        # linha horizontal com esticadores dos dois lados e o que o
        # mantem centralizado.
        self._mascot = MascotWidget(MASCOT_HEIGHT)
        mascot_row = QHBoxLayout()
        mascot_row.addStretch()
        mascot_row.addWidget(self._mascot)
        mascot_row.addStretch()

        self._main_label = QLabel("Arraste seus arquivos aqui")
        self._main_label.setObjectName("dropTitle")
        self._main_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._hint_label = QLabel("ou clique para selecionar")
        self._hint_label.setObjectName("hintLabel")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch()
        layout.addLayout(mascot_row)
        layout.addWidget(self._main_label)
        layout.addWidget(self._hint_label)
        layout.addStretch()

    # --- Tamanho ---------------------------------------------------------

    def set_compact(self, compact: bool) -> None:
        """Alterna entre a área grande (lista vazia) e a faixa (com arquivos).

        Enquanto não há arquivo nenhum, arrastar é a única coisa a se
        fazer na janela, e a área ocupa o espaço à altura disso. Assim
        que a lista tem conteúdo, o assunto passa a ser a lista: a área
        encolhe para uma faixa que continua recebendo arquivos novos, e
        o mascote encolhe junto em vez de sumir — ele é quem reage ao
        que está acontecendo.
        """
        if compact == self._compact:
            return
        self._compact = compact

        self.setMinimumHeight(DROP_HEIGHT_COMPACT if compact else DROP_HEIGHT)
        self._mascot.set_height(MASCOT_HEIGHT_COMPACT if compact else MASCOT_HEIGHT)
        self._layout.setSpacing(4 if compact else 8)

        self._main_label.setText(
            "Arraste mais arquivos aqui" if compact else "Arraste seus arquivos aqui"
        )
        self._main_label.setProperty("compact", "true" if compact else "false")
        self._main_label.style().unpolish(self._main_label)
        self._main_label.style().polish(self._main_label)

        # Na faixa, "ou clique para selecionar" sai: a área inteira já
        # é clicável, e o cursor diz isso — a linha extra só gastaria a
        # altura que acabou de ser devolvida à lista.
        self._hint_label.setVisible(not compact)

    # --- Mascote ---------------------------------------------------------

    def set_mascot_state(self, state: MascotState) -> None:
        """Repassa o estado para o mascote.

        A area de arrastar e quem abriga a figura, mas quem sabe o que
        esta acontecendo com os arquivos e a janela principal - daqui so
        passa o recado.
        """
        self._mascot.set_state(state)

    def set_mascot_animated(self, animated: bool) -> None:
        self._mascot.set_animated(animated)

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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_file_dialog()
        super().mousePressEvent(event)

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
