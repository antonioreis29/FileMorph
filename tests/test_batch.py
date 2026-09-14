"""
Testes do acompanhamento de um lote (`app/core/batch.py`).

O que está sendo protegido: cada aviso da fila chega a *todos* os arquivos
da tarefa — inclusive numa junção, em que uma tarefa só cuida da lista
inteira —, e a barra de progresso e o resumo final contam certo quando o
lote é cancelado ou quando uma tarefa levanta exceção.

Sem Qt: o `BatchTracker` é alimentado direto, ou por uma
`SynchronousTaskQueue` rodando tarefas planejadas de verdade.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.batch import (
    CONVERT,
    MERGE,
    ORGANIZE,
    BatchTracker,
    FileStatus,
    PlannedTask,
    new_task_id,
)
from app.core.converter import ConversionResult
from app.core.merger import MergeResult
from app.core.task_context import OperationCancelled
from app.core.task_runner import SynchronousTaskQueue


def _task(kind: str, paths: list[str], output: str | None = None, run=None) -> PlannedTask:
    return PlannedTask(
        task_id=new_task_id(kind),
        kind=kind,
        affected_paths=tuple(paths),
        output_path=output,
        run=run or (lambda _context: None),
    )


def _statuses(tracker: BatchTracker, paths: list[str]) -> list[FileStatus | None]:
    return [tracker.status_of(p) for p in paths]


def _feed(tracker: BatchTracker, queue: SynchronousTaskQueue) -> None:
    """Liga a fila síncrona ao acompanhamento, como o controlador da janela faz."""
    queue.on_started = tracker.task_started
    queue.on_finished = tracker.task_finished
    queue.on_failed = tracker.task_failed
    queue.on_cancelled = tracker.task_cancelled
    queue.on_progress = tracker.task_progress


# --- Junção --------------------------------------------------------------------------


FILES = ["C:/docs/a.pdf", "C:/docs/b.png", "C:/docs/c.pdf"]


def test_merge_start_marks_every_file_as_processing() -> None:
    task = _task(MERGE, FILES, "C:/saida/final.pdf")
    tracker = BatchTracker(MERGE, [task], "C:/saida")

    updates = tracker.task_started(task.task_id)

    assert [u.path for u in updates] == FILES
    assert _statuses(tracker, FILES) == [FileStatus.PROCESSING] * 3
    assert tracker.current_label(task.task_id) == "final.pdf"


def test_cancelled_merge_marks_all_files_and_counts_right() -> None:
    task = _task(MERGE, FILES, "C:/saida/final.pdf")
    tracker = BatchTracker(MERGE, [task], "C:/saida")
    tracker.task_started(task.task_id)
    tracker.task_progress(task.task_id, 40)

    tracker.request_cancel()
    updates = tracker.task_cancelled(task.task_id)

    assert [u.status for u in updates] == [FileStatus.CANCELLED] * 3
    assert tracker.is_finished()
    assert tracker.progress() == (3, 100)
    summary = tracker.summary()
    assert summary.cancelled
    assert summary.succeeded == ()
    assert summary.stopped == tuple(FILES)
    assert summary.failed == ()


def test_merge_raising_an_exception_marks_all_files_as_error() -> None:
    task = _task(MERGE, FILES, "C:/saida/final.pdf")
    tracker = BatchTracker(MERGE, [task], "C:/saida")
    tracker.task_started(task.task_id)

    updates = tracker.task_failed(task.task_id, "falha inesperada")

    assert [(u.status, u.message) for u in updates] == [(FileStatus.ERROR, "falha inesperada")] * 3
    summary = tracker.summary()
    assert summary.failed == tuple((p, "falha inesperada") for p in FILES)
    assert summary.succeeded == ()
    assert tracker.progress() == (3, 100)


def test_merge_through_a_real_queue_with_an_exception() -> None:
    """O mesmo caso, com a tarefa rodando numa fila: a exceção vira aviso de
    falha, e o aviso chega aos três arquivos."""

    def explode(_context):
        raise RuntimeError("o merger quebrou")

    task = _task(MERGE, FILES, "C:/saida/final.pdf", run=explode)
    tracker = BatchTracker(MERGE, [task], "C:/saida")
    queue = SynchronousTaskQueue()
    _feed(tracker, queue)

    queue.enqueue(task.task_id, task.run)

    assert _statuses(tracker, FILES) == [FileStatus.ERROR] * 3
    assert tracker.summary().failed[0][1] == "o merger quebrou"


def test_merge_cancelled_before_it_starts_through_a_real_queue() -> None:
    task = _task(MERGE, FILES, "C:/saida/final.pdf")
    tracker = BatchTracker(MERGE, [task], "C:/saida")
    queue = SynchronousTaskQueue(autorun=False)
    _feed(tracker, queue)

    queue.enqueue(task.task_id, task.run)
    tracker.request_cancel()
    queue.cancel_all()
    queue.run_pending()

    assert _statuses(tracker, FILES) == [FileStatus.CANCELLED] * 3
    assert tracker.summary().stopped == tuple(FILES)


def test_merge_success_summary_points_to_the_output_folder() -> None:
    task = _task(MERGE, FILES, "C:/saida/final.pdf")
    tracker = BatchTracker(MERGE, [task], "C:/outra")

    tracker.task_finished(task.task_id, MergeResult(True, FILES, "C:/saida/final.pdf"))

    summary = tracker.summary()
    assert summary.succeeded == tuple(FILES)
    assert summary.output_path == "C:/saida/final.pdf"
    assert Path(summary.output_folder) == Path("C:/saida")


# --- Conversão e organização -----------------------------------------------------------


def test_convert_batch_mixing_success_error_and_cancel() -> None:
    paths = ["a.png", "b.png", "c.png", "d.png"]
    tasks = [_task(CONVERT, [p]) for p in paths]
    tracker = BatchTracker(CONVERT, tasks, "C:/saida")

    tracker.task_finished(tasks[0].task_id, ConversionResult(True, "a.png", "C:/saida/a.jpg"))
    tracker.task_finished(tasks[1].task_id, ConversionResult(False, "b.png", error_message="ruim"))
    assert tracker.progress() == (2, 50)

    tracker.task_progress(tasks[2].task_id, 50)
    assert tracker.progress() == (2, round((200 + 50) / 4))

    tracker.request_cancel()
    tracker.task_cancelled(tasks[2].task_id)
    tracker.task_cancelled(tasks[3].task_id)

    summary = tracker.summary()
    assert summary.succeeded == ("a.png",)
    assert summary.failed == (("b.png", "ruim"),)
    assert summary.stopped == ("c.png", "d.png")
    assert summary.output_folder == "C:/saida"
    assert summary.output_path is None
    assert tracker.progress() == (4, 100)


def test_organize_task_updates_its_file() -> None:
    task = _task(ORGANIZE, ["C:/docs/relatorio.pdf"], "C:/saida/relatorio_reorganizado.pdf")
    tracker = BatchTracker(ORGANIZE, [task], "C:/saida")

    tracker.task_started(task.task_id)
    assert tracker.current_label(task.task_id) == "relatorio.pdf"
    tracker.task_finished(task.task_id, ConversionResult(True, "C:/docs/relatorio.pdf"))

    assert tracker.status_of("C:/docs/relatorio.pdf") == FileStatus.DONE
    assert tracker.summary().output_path == "C:/saida/relatorio_reorganizado.pdf"


def test_signals_from_other_tasks_or_late_signals_are_ignored() -> None:
    task = _task(CONVERT, ["a.png"])
    tracker = BatchTracker(CONVERT, [task], "C:/saida")

    assert tracker.task_started("convert:outro-lote") == []
    assert not tracker.task_progress("convert:outro-lote", 50)
    tracker.task_cancelled(task.task_id)
    # Um resultado atrasado não reescreve o cancelamento.
    assert tracker.task_finished(task.task_id, ConversionResult(True, "a.png")) == []
    assert tracker.status_of("a.png") == FileStatus.CANCELLED


def test_a_real_task_that_cancels_itself_is_reported_as_cancelled() -> None:
    def stops(_context):
        raise OperationCancelled()

    task = _task(CONVERT, ["a.png"], run=stops)
    tracker = BatchTracker(CONVERT, [task], "C:/saida")
    queue = SynchronousTaskQueue()
    _feed(tracker, queue)

    queue.enqueue(task.task_id, task.run)

    assert tracker.status_of("a.png") == FileStatus.CANCELLED


@pytest.mark.parametrize("percent", [-20, 150])
def test_progress_is_clamped(percent: int) -> None:
    task = _task(CONVERT, ["a.png"])
    tracker = BatchTracker(CONVERT, [task], "C:/saida")

    tracker.task_progress(task.task_id, percent)

    assert 0 <= tracker.progress()[1] <= 100


def test_task_ids_are_unique_even_for_the_same_destination() -> None:
    assert new_task_id(MERGE) != new_task_id(MERGE)
