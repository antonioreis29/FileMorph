"""
Testes da janela de organização de páginas e da sua ligação com a janela
principal. Os testes do lote na janela principal (junção cancelada ou
quebrada, progresso e resumo) estão em `test_main_window.py`.

A regra da ordem já é testada sem interface em `test_page_organizer.py`.
Aqui o que se confere é o que só existe na tela: que a numeração mostrada
acompanha as mudanças, que a seleção vai junto com a página arrastada, que
a grade entende onde a página foi solta, que os botões de mover, restaurar,
cancelar e salvar fazem o que dizem — e que, no fim, a janela principal
leva a ordem escolhida até o arquivo gravado.

Rodam com a plataforma "offscreen" do Qt, sem abrir janela nenhuma (ver
`conftest.py`, que cria a aplicação Qt da suíte). Todo diálogo modal
(salvar arquivo, avisos) e a abertura da pasta ao concluir são
substituídos, para que o teste nunca pare esperando um clique nem abra
nada na máquina de quem roda a suíte.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="A janela é construída sobre Qt")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.page_organizer import PageOrganizerError, PagePreview, PageThumbnail  # noqa: E402
from app.ui import page_organizer_dialog as dialog_module  # noqa: E402
from app.ui.page_organizer_dialog import (  # noqa: E402
    PageCardDelegate,
    PageGridView,
    PageOrderModel,
    PageOrganizerDialog,
)
from app.ui.page_order_model import THUMBNAIL_FAILED_ROLE  # noqa: E402
from app.ui.styles import build_stylesheet, get_palette  # noqa: E402

_TIMEOUT_SECONDS = 5.0


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        return QApplication([])
    if not isinstance(app, QApplication):
        pytest.skip("Já existe uma QCoreApplication sem interface neste processo.")
    return app


def _spin_until(app: QApplication, condition, timeout: float = _TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class _FakePreview(PagePreview):
    """Um documento de mentira: páginas em branco, desenhadas na hora."""

    def __init__(self, page_count: int, broken_pages: tuple[int, ...] = ()) -> None:
        self._page_count = page_count
        self._broken = set(broken_pages)
        self.rendered: list[int] = []
        self.closed = False

    @property
    def page_count(self) -> int:
        return self._page_count

    def render_thumbnail(self, page_index: int, max_side: int) -> PageThumbnail:
        if page_index in self._broken:
            raise RuntimeError("página ilegível")
        self.rendered.append(page_index)
        width, height = max(1, max_side * 7 // 10), max_side
        return PageThumbnail(width, height, bytes([250]) * (width * height * 3))

    def close(self) -> None:
        self.closed = True


def _open_dialog(
    qt_app: QApplication,
    tmp_path: Path,
    preview: _FakePreview | None = None,
    opener=None,
) -> PageOrganizerDialog:
    source = tmp_path / "relatorio.pdf"
    source.write_bytes(b"%PDF-1.4 o documento de verdade nao e lido: a previa e falsa")
    dialog = PageOrganizerDialog(
        str(source),
        opener or (lambda _path: preview),
        get_palette("light"),
        str(tmp_path / "saida"),
    )
    dialog.setStyleSheet(build_stylesheet(get_palette("light")))
    dialog.show()
    if preview is not None:
        assert _spin_until(qt_app, lambda: dialog._model.rowCount() == preview.page_count)
    return dialog


def _close(qt_app: QApplication, dialog: PageOrganizerDialog) -> None:
    dialog._model.restore_original_order()  # sem a pergunta de descarte
    dialog.reject()
    qt_app.processEvents()


# --- Modelo ----------------------------------------------------------------------


def test_model_starts_in_the_original_order(qt_app: QApplication) -> None:
    model = PageOrderModel()
    model.set_page_count(4)

    assert model.page_order() == [0, 1, 2, 3]
    assert model.is_original_order()
    assert model.index(0, 0).data() == "Página 1"


def test_moving_updates_numbering_and_keeps_every_page(qt_app: QApplication) -> None:
    model = PageOrderModel()
    model.set_page_count(4)
    changes: list[bool] = []
    model.order_changed.connect(lambda: changes.append(True))

    start = model.move_rows([2], 0)

    assert start == 0
    assert model.page_order() == [2, 0, 1, 3]
    assert not model.is_original_order()
    # A primeira posição agora mostra a página 3, e diz de onde ela veio.
    assert model.index(0, 0).data() == "Página 3"
    assert "agora na posição 1" in model.index(0, 0).data(Qt.ItemDataRole.ToolTipRole)
    assert changes == [True]


def test_a_move_that_changes_nothing_is_not_reported(qt_app: QApplication) -> None:
    model = PageOrderModel()
    model.set_page_count(3)
    changes: list[bool] = []
    model.order_changed.connect(lambda: changes.append(True))

    model.move_rows([1], 1)

    assert changes == []


def test_selection_follows_the_moved_page(qt_app: QApplication) -> None:
    model = PageOrderModel()
    model.set_page_count(5)
    selection = QItemSelectionModel(model)
    selection.select(model.index(3, 0), QItemSelectionModel.SelectionFlag.Select)

    model.move_rows([3], 0)

    assert [index.row() for index in selection.selectedIndexes()] == [0]


def test_restoring_brings_back_the_original_order(qt_app: QApplication) -> None:
    model = PageOrderModel()
    model.set_page_count(4)
    model.move_rows([3], 0)

    model.restore_original_order()

    assert model.page_order() == [0, 1, 2, 3]
    assert model.is_original_order()


def test_thumbnail_memory_is_bounded(qt_app: QApplication) -> None:
    model = PageOrderModel(thumbnail_limit=3)
    model.set_page_count(6)
    image = QImage(4, 4, QImage.Format.Format_RGB32)

    for page in range(5):
        model.set_thumbnail(page, image)

    assert [page for page in range(6) if model.needs_thumbnail(page)] == [0, 1, 5]


def test_a_page_without_preview_is_not_requested_again(qt_app: QApplication) -> None:
    model = PageOrderModel()
    model.set_page_count(3)

    model.set_thumbnail(1, QImage())

    assert not model.needs_thumbnail(1)
    assert model.index(1, 0).data(THUMBNAIL_FAILED_ROLE) is True
    # A página continua no documento: só não tem desenho.
    assert model.page_order() == [0, 1, 2]


# --- Grade --------------------------------------------------------------------------


@pytest.fixture
def grid(qt_app: QApplication):
    model = PageOrderModel()
    model.set_page_count(10)
    view = PageGridView()
    view.setModel(model)
    view.setItemDelegate(PageCardDelegate(get_palette("light"), view))
    view.resize(720, 460)
    view.show()
    assert _spin_until(qt_app, lambda: view.visualRect(model.index(1, 0)).isValid())
    yield view, model
    view.close()


def test_drop_on_the_left_half_inserts_before_the_card(grid) -> None:
    view, model = grid
    rect = view.visualRect(model.index(1, 0))

    assert view.insertion_row_at(QPoint(rect.left() + 5, rect.center().y())) == 1
    assert view.insertion_row_at(QPoint(rect.right() - 5, rect.center().y())) == 2


def test_drop_below_the_last_card_goes_to_the_end(qt_app: QApplication, grid) -> None:
    view, model = grid
    model.set_page_count(3)  # uma linha só, com espaço vazio embaixo
    assert _spin_until(qt_app, lambda: view.visualRect(model.index(2, 0)).isValid())
    last = view.visualRect(model.index(2, 0))

    assert view.insertion_row_at(QPoint(5, last.bottom() + 40)) == 3


def test_cards_fill_the_width_without_leaving_the_last_column_out(grid) -> None:
    view, model = grid
    first_line = view._last_row_in_line(0) + 1
    last_in_line = view.visualRect(model.index(first_line - 1, 0))

    assert first_line >= 2
    assert last_in_line.right() < view.viewport().width()
    # Nenhum vão entre os cards: a célula seguinte começa onde a outra acaba.
    assert view.visualRect(model.index(1, 0)).left() == view.visualRect(model.index(0, 0)).right() + 1


def test_visible_rows_come_first_and_nothing_repeats(grid) -> None:
    view, model = grid

    rows = view.rows_near_viewport()

    assert rows[0] == 0
    assert len(rows) == len(set(rows))
    assert all(0 <= row < model.rowCount() for row in rows)


def _drag_over(view: PageGridView, mime: QMimeData, position: QPoint) -> tuple[bool, bool]:
    """Envia à grade o que o sistema envia ao arrastar algo sobre ela.

    O arrastar do sistema operacional não existe na plataforma offscreen
    (lá, `QDrag.exec` volta na hora), então os eventos são entregues
    diretamente ao viewport — os mesmos que o Qt entregaria.
    """
    buttons, modifiers = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    enter = QDragEnterEvent(position, Qt.DropAction.MoveAction, mime, buttons, modifiers)
    QApplication.sendEvent(view.viewport(), enter)
    move = QDragMoveEvent(position, Qt.DropAction.MoveAction, mime, buttons, modifiers)
    QApplication.sendEvent(view.viewport(), move)
    return enter.isAccepted(), move.isAccepted()


def _drop(view: PageGridView, mime: QMimeData, position: QPoint) -> bool:
    event = QDropEvent(
        QPointF(position),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view.viewport(), event)
    return event.isAccepted()


def test_dropping_a_page_on_the_right_half_of_a_card_puts_it_after(grid) -> None:
    view, model = grid
    view.pages_dropped.connect(model.move_rows)
    target = view.visualRect(model.index(2, 0))
    position = QPoint(target.right() - 10, target.center().y())
    mime = view.mime_for_rows([0])

    assert _drag_over(view, mime, position) == (True, True)
    # A marca de soltura aparece à direita do card de destino.
    assert view._drop_marker == (2, True)

    assert _drop(view, mime, position)
    assert model.page_order() == [1, 2, 0, 3, 4, 5, 6, 7, 8, 9]
    assert view._drop_marker is None


def test_several_selected_pages_are_dropped_together(grid) -> None:
    view, model = grid
    view.pages_dropped.connect(model.move_rows)
    target = view.visualRect(model.index(0, 0))
    position = QPoint(target.left() + 5, target.center().y())
    mime = view.mime_for_rows([5, 7])

    _drag_over(view, mime, position)
    assert _drop(view, mime, position)

    assert model.page_order() == [5, 7, 0, 1, 2, 3, 4, 6, 8, 9]


def test_files_and_pages_from_another_window_are_refused(grid) -> None:
    """Um arquivo arrastado do Explorer não é página, e páginas de outra
    janela de organização são posições de outro documento."""
    view, model = grid
    view.pages_dropped.connect(model.move_rows)
    position = view.visualRect(model.index(1, 0)).center()
    files = QMimeData()
    files.setUrls([QUrl.fromLocalFile("C:/documentos/outro.pdf")])
    other_window = PageGridView()
    foreign_pages = other_window.mime_for_rows([0])

    for mime in (files, foreign_pages):
        assert _drag_over(view, mime, position) == (False, False)
        assert not _drop(view, mime, position)

    assert model.page_order() == list(range(10))
    other_window.deleteLater()


def test_ctrl_arrows_ask_to_move_the_selection(qt_app: QApplication, grid) -> None:
    view, _model = grid
    requests: list[str] = []
    view.move_requested.connect(requests.append)

    QTest.keyClick(view, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(view, Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)

    assert requests == ["forward", "start"]


# --- Janela de organização -------------------------------------------------------------


def test_dialog_shows_the_pages_and_loads_the_visible_thumbnails(
    qt_app: QApplication, tmp_path: Path
) -> None:
    preview = _FakePreview(6)
    dialog = _open_dialog(qt_app, tmp_path, preview)
    try:
        assert _spin_until(qt_app, lambda: not dialog._model.needs_thumbnail(0))
        assert dialog._count_badge.text() == "6 páginas"
        # Na ordem original não há o que salvar.
        assert not dialog._save_button.isEnabled()
        assert "Ordem original" in dialog._summary.full_text()
    finally:
        _close(qt_app, dialog)
    assert preview.closed  # fechar a janela libera o documento


def test_dropping_pages_reorders_and_updates_the_summary(
    qt_app: QApplication, tmp_path: Path
) -> None:
    dialog = _open_dialog(qt_app, tmp_path, _FakePreview(4))
    try:
        dialog._view.pages_dropped.emit([2], 0)

        assert dialog.page_order() == [2, 0, 1, 3]
        assert dialog._summary.full_text() == "Nova ordem: 3, 1, 2, 4"
        assert dialog._save_button.isEnabled()
    finally:
        _close(qt_app, dialog)


def test_move_buttons_act_on_the_selected_pages(qt_app: QApplication, tmp_path: Path) -> None:
    dialog = _open_dialog(qt_app, tmp_path, _FakePreview(5))
    try:
        selection = dialog._view.selectionModel()
        selection.select(dialog._model.index(3, 0), QItemSelectionModel.SelectionFlag.Select)

        dialog._move_buttons["start"].click()
        assert dialog.page_order() == [3, 0, 1, 2, 4]

        dialog._move_buttons["forward"].click()
        assert dialog.page_order() == [0, 3, 1, 2, 4]

        dialog._move_buttons["end"].click()
        assert dialog.page_order() == [0, 1, 2, 4, 3]

        dialog._restore_button.click()
        assert dialog.page_order() == [0, 1, 2, 3, 4]
    finally:
        _close(qt_app, dialog)


def test_saving_confirms_the_order_and_the_file_name(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preview = _FakePreview(4)
    dialog = _open_dialog(qt_app, tmp_path, preview)
    chosen = tmp_path / "saida" / "relatorio_novo"
    offered: list[str] = []

    class _SaveDialog:
        @staticmethod
        def getSaveFileName(_parent, _title, suggestion, _filter):  # noqa: N802 — nome do Qt
            offered.append(suggestion)
            return str(chosen), ""

    monkeypatch.setattr(dialog_module, "QFileDialog", _SaveDialog)
    dialog._view.pages_dropped.emit([3], 0)

    dialog._save_button.click()

    assert dialog.result() == PageOrganizerDialog.DialogCode.Accepted
    assert dialog.page_order() == [3, 0, 1, 2]
    # A extensão é completada, e a sugestão não pisa em nada que já exista.
    assert dialog.output_path() == f"{chosen}.pdf"
    assert Path(offered[0]).name == "relatorio_reorganizado.pdf"
    assert preview.closed


def test_saving_over_the_original_is_refused(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = _open_dialog(qt_app, tmp_path, _FakePreview(3))
    warnings: list[str] = []

    class _SaveDialog:
        @staticmethod
        def getSaveFileName(*_args):  # noqa: N802 — nome do Qt
            return str(tmp_path / "relatorio.pdf"), ""

    class _MessageBox:
        @staticmethod
        def warning(_parent, title, _text):
            warnings.append(title)

    monkeypatch.setattr(dialog_module, "QFileDialog", _SaveDialog)
    monkeypatch.setattr(dialog_module, "QMessageBox", _MessageBox)
    try:
        dialog._view.pages_dropped.emit([2], 0)
        dialog._save_button.click()

        assert warnings == ["Escolha outro nome"]
        assert dialog.isVisible()
        assert dialog.output_path() is None
    finally:
        monkeypatch.undo()
        _close(qt_app, dialog)


def test_cancelling_with_changes_asks_before_discarding(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = _open_dialog(qt_app, tmp_path, _FakePreview(3))
    answers = iter([False, True])
    monkeypatch.setattr(dialog, "_confirm_discard", lambda: next(answers))
    dialog._view.pages_dropped.emit([2], 0)

    dialog._cancel_button.click()
    assert dialog.isVisible()  # "Continuar organizando"

    dialog._cancel_button.click()
    assert not dialog.isVisible()  # "Descartar"
    assert dialog.result() == PageOrganizerDialog.DialogCode.Rejected


def test_single_page_document_has_nothing_to_reorder(
    qt_app: QApplication, tmp_path: Path
) -> None:
    dialog = _open_dialog(qt_app, tmp_path, _FakePreview(1))
    try:
        assert "uma página só" in dialog._summary.full_text()
        assert not dialog._save_button.isEnabled()
        assert not any(button.isEnabled() for button in dialog._move_buttons.values())
    finally:
        _close(qt_app, dialog)


def test_a_page_that_cannot_be_drawn_stays_in_the_document(
    qt_app: QApplication, tmp_path: Path
) -> None:
    dialog = _open_dialog(qt_app, tmp_path, _FakePreview(3, broken_pages=(1,)))
    try:
        assert _spin_until(qt_app, lambda: not dialog._model.needs_thumbnail(1))
        assert dialog._model.index(1, 0).data(THUMBNAIL_FAILED_ROLE)
        assert dialog.page_order() == [0, 1, 2]
    finally:
        _close(qt_app, dialog)


def test_document_that_cannot_be_opened_explains_itself(
    qt_app: QApplication, tmp_path: Path
) -> None:
    def protected(_path: str) -> PagePreview:
        raise PageOrganizerError("'relatorio.pdf' está protegido por senha.")

    dialog = _open_dialog(qt_app, tmp_path, opener=protected)
    try:
        assert _spin_until(qt_app, lambda: "senha" in dialog._message.text())
        assert not dialog._save_button.isEnabled()
        assert dialog._cancel_button.text() == "Fechar"
    finally:
        _close(qt_app, dialog)


# --- Da janela principal ao arquivo gravado ---------------------------------------------


@pytest.mark.integration
def test_main_window_organizes_a_pdf_end_to_end(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O caminho inteiro: modo Organizar, a janela devolve a nova ordem, e a
    fila grava o PDF com as páginas nessa ordem."""
    pymupdf = pytest.importorskip("pymupdf")
    from app.config.settings import settings_manager
    from app.organizers import register_builtin_organizers
    from app.ui import main_window as main_window_module
    from app.ui.file_list import FileStatus
    from app.ui.main_window import MainWindow

    register_builtin_organizers()

    source = tmp_path / "relatorio.pdf"
    document = pymupdf.open()
    for number in range(1, 5):
        document.new_page().insert_text((40, 80), f"Pagina {number}", fontsize=20)
    document.save(source)
    document.close()
    destination = tmp_path / "saida" / "relatorio_reorganizado.pdf"

    class _ChosenOrder:
        """Faz o papel do usuário na janela de organização."""

        def __init__(self, path, _open_preview, _palette, _output_dir, parent=None) -> None:
            assert path == str(source)

        def exec(self) -> bool:
            return True

        def output_path(self) -> str:
            return str(destination)

        def page_order(self) -> list[int]:
            return [2, 0, 3, 1]

    summaries: list[str] = []
    opened_folders: list[str] = []

    monkeypatch.setattr(main_window_module, "PageOrganizerDialog", _ChosenOrder)
    monkeypatch.setattr(
        MainWindow,
        "_show_summary",
        lambda _self, _title, text, **_options: summaries.append(text) or False,
    )
    monkeypatch.setattr(MainWindow, "_open_folder", staticmethod(opened_folders.append))
    monkeypatch.setattr(settings_manager.settings, "output_folder", str(tmp_path / "saida"))

    window = MainWindow()
    try:
        window._file_list.add_files([str(source)])
        window._organize_button.click()

        assert window._primary_button.text() == "ORGANIZAR PÁGINAS"
        assert window._primary_button.isEnabled()
        assert window._organize_file.full_text() == "relatorio.pdf"

        window._primary_button.click()

        assert _spin_until(qt_app, lambda: bool(summaries))
        assert summaries == [
            f"PDF salvo com a nova ordem das páginas em:\n{destination}"
        ]
        with pymupdf.open(destination) as reordered:
            assert [page.get_text().strip() for page in reordered] == [
                "Pagina 3",
                "Pagina 1",
                "Pagina 4",
                "Pagina 2",
            ]
        assert window._file_list._cards[str(source)].entry.status == FileStatus.DONE
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_main_window_explains_what_organizing_needs(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.organizers import register_builtin_organizers
    from app.ui.main_window import MainWindow

    register_builtin_organizers()
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    other = tmp_path / "b.pdf"
    other.write_bytes(b"%PDF-1.4")

    window = MainWindow()
    try:
        window._organize_button.click()
        window._file_list.add_files([str(pdf), str(other)])

        assert not window._primary_button.isEnabled()
        assert window._organize_hint.text() == (
            "Para organizar as páginas, deixe apenas um arquivo PDF na lista."
        )

        window._file_list.remove_file(str(other))
        assert window._primary_button.isEnabled()
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_organize_task_points_to_the_file_in_the_list(tmp_path: Path) -> None:
    """A tarefa diz qual arquivo da lista ela afeta — sem que ninguém precise
    interpretar o texto do id."""
    from app.core.processor import FileProcessor

    task = FileProcessor().plan_organize(
        "C:/docs/relatorio.pdf", str(tmp_path / "saida.pdf"), [1, 0]
    )

    assert task.affected_paths == ("C:/docs/relatorio.pdf",)
    assert "relatorio" not in task.task_id
