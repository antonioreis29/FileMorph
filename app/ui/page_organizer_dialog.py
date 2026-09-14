"""
Janela de organização de páginas.

Mostra as páginas de um documento como cards em grade — a miniatura, a
posição no arquivo novo e o número da página no original — e deixa o
usuário mudar a ordem arrastando e soltando. Nada é gravado aqui: a
janela devolve a ordem escolhida e o nome do arquivo novo, e quem grava é
a fila, pelo `FileProcessor` — o mesmo caminho de uma conversão, com
progresso, cancelamento e resumo final.

As peças da janela moram cada uma no seu módulo: a ordem e as miniaturas
guardadas em `page_order_model.py`, a grade com o arrastar e soltar em
`page_grid.py`, e o desenho das miniaturas em segundo plano em
`thumbnail_loader.py`. Este módulo junta as três e cuida do que é da
janela: o resumo da ordem, os botões, salvar e sair.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.page_organizer import PagePreview, describe_page_order, is_original_order
from app.ui.file_list import ElidedLabel
from app.ui.page_grid import THUMBNAIL_SIDE, PageCardDelegate, PageGridView
from app.ui.page_order_model import PageOrderModel
from app.ui.styles import Palette
from app.ui.thumbnail_loader import ThumbnailLoader
from app.utils.file_utils import (
    ensure_directory,
    get_extension,
    get_filename,
    get_stem,
    get_unique_path,
    is_same_file,
)

__all__ = ["PageCardDelegate", "PageGridView", "PageOrderModel", "PageOrganizerDialog"]

# Até quantas partes o resumo da ordem mostra antes das reticências.
_SUMMARY_MAX_PARTS = 16


class PageOrganizerDialog(QDialog):
    """Janela onde o usuário reorganiza as páginas de um documento.

    Depois de `exec()` aceito, `page_order()` e `output_path()` dizem o que
    gravar. A janela não grava nada: ver o cabeçalho do módulo.
    """

    def __init__(
        self,
        input_path: str,
        open_preview: Callable[[str], PagePreview],
        palette: Palette,
        output_dir: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Organizar páginas — FileMorph")
        self.setMinimumSize(540, 480)
        self._resize_to_screen(800, 700)

        self._input_path = input_path
        self._output_dir = output_dir
        self._output_path: str | None = None
        self._page_count = 0

        layout = QVBoxLayout(self)
        # As mesmas margens da janela de configurações.
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        layout.addLayout(self._build_header())

        self._hint = QLabel(
            "Arraste as páginas para mudar a ordem — com Ctrl ou Shift dá para "
            "selecionar e mover várias de uma vez. O número em destaque é a "
            "posição no arquivo novo."
        )
        self._hint.setObjectName("hintLabel")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._model = PageOrderModel(self)
        self._model.order_changed.connect(self._on_order_changed)

        self._view = PageGridView()
        self._view.setModel(self._model)
        self._view.setItemDelegate(PageCardDelegate(palette, self._view))
        self._view.set_palette_colors(palette)
        self._view.pages_dropped.connect(self._on_pages_dropped)
        self._view.move_requested.connect(self._move_selection)
        self._view.selectionModel().selectionChanged.connect(self._update_controls)
        self._view.verticalScrollBar().valueChanged.connect(self._schedule_thumbnail_request)
        self._view.viewport_resized.connect(self._schedule_thumbnail_request)

        self._message = QLabel("Abrindo o documento…")
        self._message.setObjectName("pageMessage")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)

        # A grade só aparece depois que o documento abre; até lá — ou se ele
        # não abrir — o espaço dela mostra a mensagem.
        self._stack = QStackedWidget()
        self._stack.addWidget(self._message)
        self._stack.addWidget(self._view)
        layout.addWidget(self._stack, 1)

        self._summary = ElidedLabel("")
        self._summary.setObjectName("orderSummary")
        layout.addWidget(self._summary)

        layout.addLayout(self._build_tools())

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)
        self._cancel_button = QPushButton("Cancelar")
        self._cancel_button.clicked.connect(self.reject)
        self._save_button = QPushButton("Salvar PDF com a nova ordem")
        self._save_button.setObjectName("primaryButton")
        self._save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_button.clicked.connect(self._on_save_clicked)
        buttons_row.addStretch()
        buttons_row.addWidget(self._cancel_button)
        buttons_row.addWidget(self._save_button)
        layout.addLayout(buttons_row)

        # Rolar dispara dezenas de avisos por segundo; o temporizador junta
        # os pedidos de miniatura num só.
        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.setInterval(40)
        self._request_timer.timeout.connect(self._request_visible_thumbnails)

        self._loader = ThumbnailLoader(
            input_path,
            open_preview,
            round(THUMBNAIL_SIDE * self.devicePixelRatio()),
            self,
        )
        self._loader.opened.connect(self._on_document_opened)
        self._loader.failed.connect(self._on_document_failed)
        self._loader.rendered.connect(self._on_thumbnail_rendered)

        self._update_controls()
        self._loader.start()

    # --- Resultado ------------------------------------------------------------

    def page_order(self) -> list[int]:
        return self._model.page_order()

    def output_path(self) -> str | None:
        return self._output_path

    # --- Construção -------------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(10)

        column = QVBoxLayout()
        column.setSpacing(0)
        title = QLabel("Organizar páginas")
        title.setObjectName("titleLabel")
        file_label = ElidedLabel(get_filename(self._input_path))
        file_label.setObjectName("taglineLabel")
        file_label.setToolTip(self._input_path)
        column.addWidget(title)
        column.addWidget(file_label)
        header.addLayout(column, 1)

        self._count_badge = QLabel("…")
        self._count_badge.setObjectName("countBadge")
        header.addWidget(self._count_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        return header

    def _build_tools(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        label = QLabel("Mover seleção:")
        label.setObjectName("hintLabel")
        row.addWidget(label)
        self._move_buttons: dict[str, QPushButton] = {}
        for action, symbol, tip in (
            ("start", "⇤", "Mover a seleção para o início (Ctrl+Home)"),
            ("back", "←", "Mover a seleção uma posição para trás (Ctrl+←)"),
            ("forward", "→", "Mover a seleção uma posição para a frente (Ctrl+→)"),
            ("end", "⇥", "Mover a seleção para o fim (Ctrl+End)"),
        ):
            button = QPushButton(symbol)
            button.setObjectName("iconButton")
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, action=action: self._move_selection(action))
            row.addWidget(button)
            self._move_buttons[action] = button
        row.addStretch()

        self._restore_button = QPushButton("Restaurar ordem original")
        self._restore_button.setObjectName("linkButton")
        self._restore_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._restore_button.clicked.connect(self._model.restore_original_order)
        row.addWidget(self._restore_button)
        return row

    def _resize_to_screen(self, width: int, height: int) -> None:
        """O tamanho pedido, ou o que couber na área útil da tela — a mesma
        preocupação da janela principal com telas baixas."""
        parent = self.parentWidget()
        screen = parent.screen() if parent is not None else QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            width = min(width, max(self.minimumWidth(), area.width() - 40))
            height = min(height, max(self.minimumHeight(), area.height() - 80))
        self.resize(width, height)

    # --- Documento e miniaturas ------------------------------------------------

    def _on_document_opened(self, page_count: int) -> None:
        self._page_count = page_count
        self._model.set_page_count(page_count)
        self._count_badge.setText(f"{page_count} página{'s' if page_count != 1 else ''}")
        self._stack.setCurrentWidget(self._view)
        self._view.setFocus()
        self._update_controls()

    def _on_document_failed(self, message: str) -> None:
        self._message.setText(message)
        self._message.setProperty("error", "true")
        self._message.style().unpolish(self._message)
        self._message.style().polish(self._message)
        self._count_badge.hide()
        self._hint.hide()
        self._cancel_button.setText("Fechar")
        self._update_controls()

    def _on_thumbnail_rendered(self, page: int, image: QImage) -> None:
        if not image.isNull():
            image.setDevicePixelRatio(self._view.devicePixelRatio())
        self._model.set_thumbnail(page, image)

    def _schedule_thumbnail_request(self) -> None:
        self._request_timer.start()

    def _request_visible_thumbnails(self) -> None:
        order = self._model.page_order()
        pages = [order[row] for row in self._view.rows_near_viewport()]
        self._loader.request([page for page in pages if self._model.needs_thumbnail(page)])

    # --- Ordem -------------------------------------------------------------------

    def _on_pages_dropped(self, rows: list[int], destination: int) -> None:
        self._apply_move(rows, destination)

    def _move_selection(self, action: str) -> None:
        rows = self._view.selected_rows()
        if not rows or self._page_count < 2:
            return
        count = self._model.rowCount()
        destination = {
            "start": 0,
            "back": max(0, rows[0] - 1),
            "forward": min(count, rows[-1] + 2),
            "end": count,
        }[action]
        self._apply_move(rows, destination)

    def _apply_move(self, rows: list[int], destination: int) -> None:
        start = self._model.move_rows(rows, destination)
        # A seleção já acompanha as páginas movidas (ver `PageOrderModel`);
        # falta levar a tela até onde elas foram parar, sem mexer nela.
        index = self._model.index(start, 0)
        self._view.selectionModel().setCurrentIndex(
            index, QItemSelectionModel.SelectionFlag.NoUpdate
        )
        self._view.scrollTo(index)

    def _on_order_changed(self) -> None:
        self._update_summary()
        self._update_controls()
        self._schedule_thumbnail_request()

    def _update_summary(self) -> None:
        order = self._model.page_order()
        modified = not is_original_order(order)
        if len(order) == 1:
            text = "Este PDF tem uma página só — não há ordem para mudar."
        elif not modified:
            text = "Ordem original: nenhuma página mudou de lugar."
        else:
            text = f"Nova ordem: {describe_page_order(order, _SUMMARY_MAX_PARTS)}"
        self._summary.setText(text if order else "")
        self._summary.setToolTip(
            f"Páginas na nova ordem: {describe_page_order(order, 200)}" if modified else ""
        )
        self._summary.setProperty("modified", "true" if modified else "false")
        self._summary.style().unpolish(self._summary)
        self._summary.style().polish(self._summary)

    def _update_controls(self) -> None:
        can_reorder = self._page_count > 1
        has_selection = bool(self._view.selected_rows())
        for button in self._move_buttons.values():
            button.setEnabled(can_reorder and has_selection)
        modified = can_reorder and not self._model.is_original_order()
        self._restore_button.setEnabled(modified)
        self._save_button.setEnabled(modified)
        self._save_button.setToolTip(
            "" if modified else "Mude a ordem das páginas para poder salvar."
        )

    # --- Salvar e sair ----------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        if self._page_count < 2 or self._model.is_original_order():
            return
        chosen, _filter = QFileDialog.getSaveFileName(
            self, "Salvar PDF com a nova ordem", str(self._suggested_output()), "PDF (*.pdf)"
        )
        if not chosen:
            return  # a janela continua aberta, com a ordem intacta
        # Em diálogos não nativos a extensão pode não vir junto do nome.
        if get_extension(chosen) != "pdf":
            chosen = f"{chosen}.pdf"
        if is_same_file(chosen, self._input_path):
            QMessageBox.warning(
                self,
                "Escolha outro nome",
                "O arquivo com a nova ordem precisa ter outro nome: o FileMorph "
                "nunca altera o arquivo original.",
            )
            return
        self._output_path = chosen
        self.accept()

    def _suggested_output(self) -> Path:
        """`<nome>_reorganizado.pdf` na pasta de saída, sem colidir com um
        arquivo que já exista. Se a pasta de saída não puder ser criada, a
        sugestão vai para a pasta do próprio PDF."""
        name = f"{get_stem(self._input_path)}_reorganizado.pdf"
        try:
            folder = ensure_directory(self._output_dir)
        except OSError:
            folder = Path(self._input_path).parent
        return get_unique_path(folder / name)

    def reject(self) -> None:
        """Cancelar, Esc e o X da janela passam por aqui. Com a ordem mudada,
        sair descartaria o trabalho — então pergunta antes."""
        if self._page_count > 1 and not self._model.is_original_order():
            if not self._confirm_discard():
                return
        super().reject()

    def done(self, result: int) -> None:
        self._request_timer.stop()
        self._loader.stop()
        super().done(result)

    def _confirm_discard(self) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Descartar a nova ordem?")
        box.setText("A nova ordem das páginas ainda não foi salva.")
        box.setInformativeText("Se sair agora, o PDF continua como estava.")
        discard_button = box.addButton("Descartar", QMessageBox.ButtonRole.DestructiveRole)
        keep_button = box.addButton("Continuar organizando", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep_button)
        box.exec()
        return box.clickedButton() is discard_button
