"""
Testes do lote na janela principal: o que o usuário vê enquanto uma
operação roda e quando ela termina.

Os casos que motivaram estes testes são os de junção. Uma junção é uma
tarefa só cuidando de todos os arquivos da lista, e antes a janela
descobria o arquivo de cada tarefa desmontando o id — o que não funcionava
para a junção. Cancelar ou quebrar uma junção deixava os cards parados em
"processando" e o resumo contando errado.

A janela roda com a fila de tarefas de verdade (threads e sinais do Qt), e
os mergers e conversores são de mentira, para o teste controlar quando cada
um termina. Diálogos modais são substituídos, para nada parar esperando um
clique.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="A janela é construída sobre Qt")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config.settings import settings_manager  # noqa: E402
from app.core.batch import FileStatus  # noqa: E402
from app.core.converter import BaseConverter, CompatibilityRegistry, ConversionResult  # noqa: E402
from app.core.merger import BaseMerger, MergeCompatibilityRegistry, MergeResult  # noqa: E402
from app.core.page_organizer import PageOrganizerRegistry  # noqa: E402
from app.core.processor import FileProcessor  # noqa: E402
from app.core.task_queue import TaskQueue  # noqa: E402
from app.ui import main_window as main_window_module  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

pytestmark = pytest.mark.integration

_TIMEOUT_SECONDS = 10.0


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        pytest.skip("Os testes de janela precisam de uma QApplication.")
    return app


def _spin_until(app: QApplication, condition, timeout: float = _TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class _ControlledMerger(BaseMerger):
    """Merger que espera o teste: fica rodando até ser cancelado, ou quebra."""

    def __init__(self, behavior: str) -> None:
        self.behavior = behavior
        self.started = threading.Event()

    @property
    def accepted_formats(self) -> set[str]:
        return {"pdf", "png"}

    @property
    def output_format(self) -> str:
        return "pdf"

    def merge(self, input_paths, output_path, context=None) -> MergeResult:
        self.started.set()
        if self.behavior == "raise":
            raise RuntimeError("o merger quebrou de propósito")
        for _ in range(1000):
            context.check_cancelled()
            context.report(30)
            time.sleep(0.01)
        return MergeResult(True, list(input_paths), output_path)


class _FakeConverter(BaseConverter):
    @property
    def source_formats(self) -> set[str]:
        return {"png", "txt"}

    @property
    def target_formats(self) -> set[str]:
        return {"jpg"}

    def convert(self, input_path, output_path, context=None) -> ConversionResult:
        if input_path.endswith(".txt"):
            return ConversionResult(False, input_path, error_message="arquivo ruim de propósito")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(f"de {input_path}", encoding="utf-8")
        return ConversionResult(True, input_path, output_path=output_path)


@pytest.fixture
def window_factory(qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Cria a janela com os registros de mentira e captura os resumos."""
    created: list[MainWindow] = []
    summaries: list[tuple[str, str]] = []
    opened: list[str] = []
    monkeypatch.setattr(settings_manager.settings, "output_folder", str(tmp_path / "saida"))
    monkeypatch.setattr(settings_manager.settings, "open_folder_after_finish", True)
    monkeypatch.setattr(settings_manager.settings, "ask_before_overwrite", False)
    monkeypatch.setattr(
        MainWindow,
        "_show_summary",
        lambda _self, title, text, **_options: summaries.append((title, text)) or False,
    )
    monkeypatch.setattr(MainWindow, "_open_folder", staticmethod(opened.append))

    def make(merger: BaseMerger | None = None, converter: BaseConverter | None = None) -> MainWindow:
        converters, mergers = CompatibilityRegistry(), MergeCompatibilityRegistry()
        if converter is not None:
            converters.register(converter)
        if merger is not None:
            mergers.register(merger)
        queue = TaskQueue(max_concurrent=2)
        processor = FileProcessor(
            queue, converters=converters, mergers=mergers, organizers=PageOrganizerRegistry()
        )
        window = MainWindow(processor=processor, task_queue=queue)
        created.append(window)
        return window

    make.summaries = summaries  # type: ignore[attr-defined]
    make.opened = opened  # type: ignore[attr-defined]
    yield make
    for window in created:
        window._batch.cancel()
        _spin_until(qt_app, lambda w=window: not w._batch.is_running(), timeout=5)
        window.close()
        window.deleteLater()
    qt_app.processEvents()


def _inputs(tmp_path: Path, names: list[str]) -> list[str]:
    paths = []
    for name in names:
        path = tmp_path / "entrada" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"conteudo original")
        paths.append(str(path))
    return paths


def _statuses(window: MainWindow, paths: list[str]) -> list[FileStatus]:
    return [window._file_list._cards[p].entry.status for p in paths]


def _start_merge(window: MainWindow, paths: list[str], destination: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        MainWindow, "_ask_merge_destination", lambda _self, _paths, _dir: str(destination)
    )
    window._file_list.add_files(paths)
    window._merge_button.click()
    assert window._primary_button.isEnabled()
    window._primary_button.click()


def test_cancelled_merge_marks_every_file_and_counts_right(
    qt_app, window_factory, tmp_path: Path, monkeypatch
) -> None:
    merger = _ControlledMerger("wait")
    window = window_factory(merger=merger)
    paths = _inputs(tmp_path, ["a.pdf", "b.png", "c.pdf"])

    _start_merge(window, paths, tmp_path / "final.pdf", monkeypatch)

    assert merger.started.wait(_TIMEOUT_SECONDS)
    assert _spin_until(qt_app, lambda: _statuses(window, paths) == [FileStatus.PROCESSING] * 3)
    assert window._progress_widget.isVisibleTo(window)
    assert window._progress_widget._current_file_label.text() == "Processando: final.pdf"

    window._progress_widget._cancel_button.click()

    assert _spin_until(qt_app, lambda: not window._batch.is_running())
    assert _statuses(window, paths) == [FileStatus.CANCELLED] * 3
    assert window_factory.summaries == [
        (
            "Operação cancelada",
            "Operação interrompida. 0 arquivo(s) já tinham sido concluídos; "
            "3 não chegaram a ser processados.",
        )
    ]
    assert not window._progress_widget.isVisibleTo(window)
    assert window._primary_button.isEnabled()
    assert window_factory.opened == []


def test_merge_that_raises_marks_every_file_as_error(
    qt_app, window_factory, tmp_path: Path, monkeypatch
) -> None:
    window = window_factory(merger=_ControlledMerger("raise"))
    paths = _inputs(tmp_path, ["a.pdf", "b.png", "c.pdf"])

    _start_merge(window, paths, tmp_path / "final.pdf", monkeypatch)

    assert _spin_until(qt_app, lambda: not window._batch.is_running())
    assert _statuses(window, paths) == [FileStatus.ERROR] * 3
    for path in paths:
        assert window._file_list._cards[path].entry.error_message == "o merger quebrou de propósito"
    title, text = window_factory.summaries[0]
    assert title == "Concluído com erros"
    assert text.startswith("0 arquivo(s) concluído(s), 3 com erro:")
    assert window._progress_widget._progress_bar.value() == 100


def test_merge_refuses_a_destination_that_is_one_of_the_inputs(
    qt_app, window_factory, tmp_path: Path, monkeypatch
) -> None:
    """A janela pede outro nome; com um nome livre, a junção segue."""
    window = window_factory(merger=_ControlledMerger("raise"))
    paths = _inputs(tmp_path, ["a.pdf", "b.pdf"])
    window._file_list.add_files(paths)
    answers = [paths[0], str(tmp_path / "livre.pdf")]
    warnings: list[str] = []

    class _FileDialog:
        @staticmethod
        def getSaveFileName(*_args, **_kwargs):  # noqa: N802 — nome do Qt
            return answers.pop(0), "PDF (*.pdf)"

    class _MessageBox:
        @staticmethod
        def warning(_parent, _title, text):
            warnings.append(text)

    monkeypatch.setattr(main_window_module, "QFileDialog", _FileDialog)
    monkeypatch.setattr(main_window_module, "QMessageBox", _MessageBox)

    chosen = window._ask_merge_destination(paths, str(tmp_path / "saida"))

    assert chosen == str(tmp_path / "livre.pdf")
    assert len(warnings) == 1 and "a.pdf" in warnings[0]
    assert Path(paths[0]).read_bytes() == b"conteudo original"


def test_convert_batch_with_success_and_error_shows_the_right_counts(
    qt_app, window_factory, tmp_path: Path
) -> None:
    window = window_factory(converter=_FakeConverter())
    paths = _inputs(tmp_path, ["boa.png", "ruim.txt"])
    other = tmp_path / "outra pasta" / "boa.png"
    other.parent.mkdir()
    other.write_bytes(b"x")
    paths.append(str(other))
    window._file_list.add_files(paths)

    window._primary_button.click()

    assert _spin_until(qt_app, lambda: not window._batch.is_running())
    assert _statuses(window, paths) == [FileStatus.DONE, FileStatus.ERROR, FileStatus.DONE]
    title, text = window_factory.summaries[0]
    assert title == "Concluído com erros"
    assert text.startswith("2 arquivo(s) concluído(s), 1 com erro:")
    # Os dois "boa.png", de pastas diferentes, não gravaram um sobre o outro.
    written = sorted(p.name for p in (tmp_path / "saida").iterdir())
    assert written == ["boa (1).jpg", "boa.jpg"]
    assert window._progress_widget._status_label.text() == "3 de 3 arquivos"
    assert window_factory.opened == [str(tmp_path / "saida")]


def test_dependency_hint_explains_what_is_missing(qt_app, window_factory, tmp_path: Path) -> None:
    window = window_factory()
    paths = _inputs(tmp_path, ["contrato.docx", "musica.mp3"])

    window._file_list.add_files(paths)

    assert window._dependency_hint.isVisibleTo(window)
    text = window._dependency_hint.text()
    assert "FFmpeg" in text and "LibreOffice" in text and "Diagnóstico" in text


class _SummaryBox:
    """Um QMessageBox de mentira, que "clica" no botão pedido."""

    clicked_text: str | None = None
    created: list["_SummaryBox"] = []

    class Icon:
        Warning = "warning"
        Information = "information"

    class ButtonRole:
        ActionRole = "action"

    class StandardButton:
        Ok = "ok"

    def __init__(self, _parent=None) -> None:
        self.buttons: list[str] = []
        _SummaryBox.created.append(self)

    def setIcon(self, _icon) -> None:  # noqa: N802 — nome do Qt
        pass

    def setWindowTitle(self, title) -> None:  # noqa: N802 — nome do Qt
        self.title = title

    def setText(self, text) -> None:  # noqa: N802 — nome do Qt
        self.text = text

    def addButton(self, button, _role=None):  # noqa: N802 — nome do Qt
        self.buttons.append(button)
        return button

    def setDefaultButton(self, _button) -> None:  # noqa: N802 — nome do Qt
        pass

    def exec(self) -> int:
        return 0

    def clickedButton(self):  # noqa: N802 — nome do Qt
        # O próprio objeto do botão, como o Qt devolve — a janela compara
        # por identidade.
        for button in self.buttons:
            if button == _SummaryBox.clicked_text:
                return button
        return None


@pytest.mark.parametrize("clicked, auto_open, expected_opens", [
    ("Abrir pasta", False, 1),  # o botão abre a pasta, mesmo sem a opção automática
    ("Abrir pasta", True, 1),   # clicou: abre uma vez, sem abrir de novo sozinho
    ("ok", True, 1),            # não clicou: a opção automática abre
    ("ok", False, 0),           # nem clique, nem opção automática
])
def test_summary_offers_to_open_the_output_folder(
    qt_app, tmp_path: Path, monkeypatch, clicked, auto_open, expected_opens
) -> None:
    opened: list[str] = []
    _SummaryBox.clicked_text = clicked
    _SummaryBox.created = []
    monkeypatch.setattr(main_window_module, "QMessageBox", _SummaryBox)
    monkeypatch.setattr(MainWindow, "_open_folder", staticmethod(opened.append))
    monkeypatch.setattr(settings_manager.settings, "open_folder_after_finish", auto_open)
    window = MainWindow(
        processor=FileProcessor(TaskQueue(), converters=CompatibilityRegistry()),
    )
    try:
        from app.core.batch import BatchSummary

        window._on_batch_finished(
            BatchSummary("convert", 1, ("a.png",), (), (), False, str(tmp_path), None)
        )
    finally:
        window.close()
        window.deleteLater()

    assert _SummaryBox.created[0].buttons[0] == "Abrir pasta"
    assert opened == [str(tmp_path)] * expected_opens


def test_settings_that_cannot_be_saved_keep_the_dialog_open(qt_app, monkeypatch) -> None:
    from app.ui import settings_window as settings_module
    from app.ui.settings_window import SettingsWindow

    warnings: list[str] = []

    class _Manager:
        settings = settings_manager.settings

        def update(self, **_values):
            raise OSError(28, "No space left on device")

    class _MessageBox:
        @staticmethod
        def warning(_parent, _title, text):
            warnings.append(text)

    monkeypatch.setattr(settings_module, "QMessageBox", _MessageBox)
    dialog = SettingsWindow(_Manager())
    accepted: list[bool] = []
    dialog.accepted.connect(lambda: accepted.append(True))
    try:
        dialog._save_and_close()
    finally:
        dialog.close()
        dialog.deleteLater()

    assert accepted == []
    assert "No space left on device" in warnings[0]


def test_about_shows_the_real_version(qt_app, window_factory, monkeypatch) -> None:
    from app.version import __version__

    window = window_factory()
    shown: list[str] = []

    class _MessageBox:
        @staticmethod
        def information(_parent, _title, text):
            shown.append(text)

    monkeypatch.setattr(main_window_module, "QMessageBox", _MessageBox)
    window._show_about()

    assert __version__ in shown[0]
    assert "Fase" not in shown[0]
