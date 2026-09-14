"""
O contrato de fila que o núcleo usa, e uma fila síncrona que o cumpre sem Qt.

`FileProcessor` precisa de alguém que execute as tarefas, mas não precisa
saber *como*. No aplicativo quem executa é a `TaskQueue`
(`app/core/task_queue.py`), construída sobre o `QThreadPool` do Qt para a
janela nunca travar. Amarrar o processador a ela, porém, obrigava qualquer
teste de regra de negócio — que destino um arquivo recebe, o que acontece
quando uma junção tenta sobrescrever uma entrada — a carregar o PySide6.

`TaskQueueProtocol` é o pouco que o processador usa da fila. Qualquer objeto
com esses métodos serve, e `SynchronousTaskQueue` é o mais simples deles:
executa cada tarefa na hora, na própria thread, entregando os mesmos avisos
que a fila de verdade entrega por sinais. Ela serve aos testes e à
verificação rápida do executável empacotado (`main.py --smoke-test`), que
precisa converter um arquivo sem abrir janela.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.task_context import OperationCancelled, TaskContext
from app.utils.logger import get_logger

logger = get_logger("core.task_runner")


class TaskQueueProtocol(Protocol):
    """O que `FileProcessor` exige de uma fila de tarefas."""

    def enqueue(self, task_id: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Agenda `func(context, *args, **kwargs)`; o `TaskContext` é da fila."""

    def cancel(self, task_id: str) -> None:
        """Pede para uma tarefa parar no próximo ponto seguro."""

    def cancel_all(self) -> None:
        """Pede para todas as tarefas pararem."""


@dataclass
class _PendingTask:
    task_id: str
    func: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    cancelled: bool = False


@dataclass
class SynchronousTaskQueue:
    """Fila sem threads: cada tarefa roda dentro de `enqueue` (ou de
    `run_pending`, com `autorun=False`).

    Os avisos são os mesmos da `TaskQueue`, em chamadas simples no lugar de
    sinais: `on_started(id)`, `on_finished(id, resultado)`,
    `on_failed(id, mensagem)`, `on_cancelled(id)`, `on_progress(id, %)` e
    `on_all_finished()`. `events` guarda tudo o que aconteceu, na ordem, para
    os testes conferirem.

    Com `autorun=False` as tarefas esperam `run_pending()`, o que permite
    cancelar uma tarefa antes de ela começar — o mesmo caso da fila real
    quando o lote tem mais arquivos que processos simultâneos.
    """

    autorun: bool = True
    on_started: Callable[[str], None] | None = None
    on_finished: Callable[[str, Any], None] | None = None
    on_failed: Callable[[str, str], None] | None = None
    on_cancelled: Callable[[str], None] | None = None
    on_progress: Callable[[str, int], None] | None = None
    on_all_finished: Callable[[], None] | None = None
    events: list[tuple[Any, ...]] = field(default_factory=list)
    _pending: list[_PendingTask] = field(default_factory=list)
    _cancel_requested: set[str] = field(default_factory=set)

    def enqueue(self, task_id: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self._pending.append(_PendingTask(task_id, func, args, kwargs))
        if self.autorun:
            self.run_pending()

    def cancel(self, task_id: str) -> None:
        self._cancel_requested.add(task_id)
        for task in self._pending:
            if task.task_id == task_id:
                task.cancelled = True

    def cancel_all(self) -> None:
        for task in self._pending:
            task.cancelled = True
            self._cancel_requested.add(task.task_id)

    def run_pending(self) -> None:
        while self._pending:
            self._run(self._pending.pop(0))
        self._emit("all_finished")

    def _run(self, task: _PendingTask) -> None:
        if task.cancelled:
            self._emit("cancelled", task.task_id)
            return
        self._emit("started", task.task_id)
        context = TaskContext(
            on_progress=lambda percent: self._emit("progress", task.task_id, percent),
            is_cancelled=lambda: task.task_id in self._cancel_requested,
        )
        try:
            result = task.func(context, *task.args, **task.kwargs)
        except OperationCancelled:
            self._emit("cancelled", task.task_id)
        except Exception as exc:  # noqa: BLE001 — o mesmo contrato da TaskQueue
            logger.error("Tarefa %s falhou: %s\n%s", task.task_id, exc, traceback.format_exc())
            self._emit("failed", task.task_id, str(exc))
        else:
            if task.task_id in self._cancel_requested:
                self._emit("cancelled", task.task_id)
            else:
                self._emit("finished", task.task_id, result)

    def _emit(self, name: str, *payload: Any) -> None:
        self.events.append((name, *payload))
        callback = getattr(self, f"on_{name}")
        if callback is not None:
            callback(*payload)
