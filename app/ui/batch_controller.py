"""
Controle do lote em andamento: a ponte entre a fila de tarefas e a janela.

A janela principal só quer saber de arquivos — qual mudou de situação, quanto
do lote já foi, qual arquivo está sendo lido, e o resumo no fim. A fila só
fala de tarefas. Quem traduz uma coisa na outra é o `BatchTracker`
(`app/core/batch.py`), que sabe, sem adivinhar nada pelo id, quais arquivos
cada tarefa afeta. Este controlador liga os sinais da fila a ele e devolve à
janela sinais já no vocabulário dela.

Um lote de cada vez: enquanto um roda, `start` recusa outro. Avisos que
chegam da fila depois de o lote terminar são ignorados pelo acompanhamento,
de modo que nenhum sinal atrasado abre diálogo fora de hora.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QObject, Signal

from app.core.batch import BatchSummary, BatchTracker, FileUpdate, PlannedTask
from app.core.processor import FileProcessor
from app.core.task_queue import TaskQueue


class BatchController(QObject):
    """Começa, acompanha e cancela o lote da janela principal."""

    # Total de arquivos do lote, emitido antes de qualquer outro aviso: é a
    # deixa para a janela montar o progresso.
    batch_started = Signal(int)
    file_updated = Signal(object)  # FileUpdate
    progress_changed = Signal(int, int)  # arquivos finalizados, percentual
    current_file_changed = Signal(str)
    batch_finished = Signal(object)  # BatchSummary

    def __init__(
        self, queue: TaskQueue, processor: FileProcessor, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._queue = queue
        self._processor = processor
        self._tracker: BatchTracker | None = None

        queue.task_started.connect(self._on_task_started)
        queue.task_finished.connect(self._on_task_finished)
        queue.task_failed.connect(self._on_task_failed)
        queue.task_cancelled.connect(self._on_task_cancelled)
        queue.task_progress.connect(self._on_task_progress)

    def is_running(self) -> bool:
        return self._tracker is not None

    def total_files(self) -> int:
        return self._tracker.total_files if self._tracker is not None else 0

    def start(self, kind: str, tasks: Sequence[PlannedTask], output_dir: str) -> None:
        """Registra o lote e só então entrega as tarefas à fila.

        A ordem importa: registrado depois, um aviso de uma tarefa rápida
        poderia chegar antes de o acompanhamento saber que ela existe.
        """
        if self._tracker is not None:
            raise RuntimeError("Já existe um lote em andamento.")
        if not tasks:
            return
        tracker = BatchTracker(kind, tasks, output_dir)
        self._tracker = tracker
        self.batch_started.emit(tracker.total_files)
        self._emit_updates(tracker.initial_updates())
        self._emit_progress()
        self._processor.submit(tasks)

    def cancel(self) -> None:
        """Pede para o lote parar. As tarefas que não começaram nem rodam; a
        que está rodando para no próximo ponto seguro."""
        if self._tracker is None:
            return
        self._tracker.request_cancel()
        self._queue.cancel_all()

    # --- Avisos da fila -------------------------------------------------------

    def _on_task_started(self, task_id: str) -> None:
        tracker = self._tracker
        if tracker is None:
            return
        updates = tracker.task_started(task_id)
        if not updates:
            return
        self._emit_updates(updates)
        label = tracker.current_label(task_id)
        if label:
            self.current_file_changed.emit(label)

    def _on_task_finished(self, task_id: str, result: object) -> None:
        if self._tracker is not None:
            self._after(self._tracker.task_finished(task_id, result))

    def _on_task_failed(self, task_id: str, message: str) -> None:
        if self._tracker is not None:
            self._after(self._tracker.task_failed(task_id, message))

    def _on_task_cancelled(self, task_id: str) -> None:
        if self._tracker is not None:
            self._after(self._tracker.task_cancelled(task_id))

    def _on_task_progress(self, task_id: str, percent: int) -> None:
        if self._tracker is not None and self._tracker.task_progress(task_id, percent):
            self._emit_progress()

    # --- Interno ---------------------------------------------------------------

    def _after(self, updates: list[FileUpdate]) -> None:
        tracker = self._tracker
        if tracker is None or not updates:
            return
        self._emit_updates(updates)
        self._emit_progress()
        if tracker.is_finished():
            summary: BatchSummary = tracker.summary()
            self._tracker = None
            self.batch_finished.emit(summary)

    def _emit_updates(self, updates: list[FileUpdate]) -> None:
        for update in updates:
            self.file_updated.emit(update)

    def _emit_progress(self) -> None:
        if self._tracker is not None:
            done, percent = self._tracker.progress()
            self.progress_changed.emit(done, percent)
