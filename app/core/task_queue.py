"""
Fila de tarefas assíncrona.

É a implementação que o aplicativo usa do `TaskQueueProtocol`
(`app/core/task_runner.py`): o `FileProcessor` só conhece o protocolo, e é
por isso que as regras de negócio podem ser testadas sem carregar o Qt.

Usa QThreadPool + QRunnable para que a interface nunca trave durante o
processamento. Cada tarefa é uma chamada `callable(context, *args)`
executada em background; o resultado (ou erro) chega de volta à
thread principal via sinais Qt, que são thread-safe por natureza.

Cada arquivo de uma conversão em lote vira uma tarefa independente, de
modo que uma falha isolada não interrompe as demais.

A fila entrega um `TaskContext` (ver
app/core/task_context.py) como primeiro argumento de toda tarefa. É
por ele que uma conversão longa informa o andamento e descobre que o
usuário pediu para parar — o que faz o cancelamento valer também para
a tarefa que já está rodando, e não só para as que ainda não
começaram.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from app.core.task_context import OperationCancelled, TaskContext


class _TaskSignals(QObject):
    """Sinais emitidos por uma tarefa individual.

    Precisam viver em um QObject separado porque QRunnable não herda
    de QObject e, portanto, não pode emitir sinais diretamente.
    """

    started = Signal(str)  # task_id
    finished = Signal(str, object)  # task_id, resultado
    failed = Signal(str, str)  # task_id, mensagem de erro
    cancelled = Signal(str)  # task_id
    progress = Signal(str, int)  # task_id, percentual 0-100


class _Task(QRunnable):
    def __init__(self, task_id: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.task_id = task_id
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.signals = _TaskSignals()
        self._cancelled = False
        # O contexto é o que a tarefa usa para reportar andamento e
        # perceber o cancelamento. É criado aqui, e não pela tarefa,
        # porque só a fila sabe para onde esses avisos devem ir.
        self.context = TaskContext(
            on_progress=lambda percent: self.signals.progress.emit(self.task_id, percent),
            is_cancelled=lambda: self._cancelled,
        )

    def cancel(self) -> None:
        """Marca a tarefa como cancelada.

        Se ela ainda não começou, `run()` detecta e nem chama `func`. Se
        já estiver em execução, a própria `func` enxerga o pedido pelo
        contexto e para no próximo ponto seguro — entre duas páginas de
        um PDF, entre dois arquivos de uma junção —, nunca no meio de
        uma gravação.
        """
        self._cancelled = True

    def run(self) -> None:
        # Uma tarefa cancelada antes de começar ainda precisa avisar a
        # fila, senão ela ficaria contada como pendente para sempre e o
        # sinal de "tudo terminou" nunca chegaria à interface.
        if self._cancelled:
            self.signals.cancelled.emit(self.task_id)
            return
        self.signals.started.emit(self.task_id)
        try:
            result = self.func(self.context, *self.args, **self.kwargs)
            if self._cancelled:
                self.signals.cancelled.emit(self.task_id)
            else:
                self.signals.finished.emit(self.task_id, result)
        except OperationCancelled:
            # Não é erro: é a tarefa obedecendo ao pedido de parar.
            self.signals.cancelled.emit(self.task_id)
        except Exception as exc:  # noqa: BLE001 — precisa capturar tudo
            # Nunca deixamos uma exceção de tarefa de background propagar
            # e derrubar a aplicação. O traceback completo
            # vai para o log; a UI recebe só a mensagem.
            from app.utils.logger import get_logger

            get_logger("core.task_queue").error(
                "Tarefa %s falhou: %s\n%s", self.task_id, exc, traceback.format_exc()
            )
            self.signals.failed.emit(self.task_id, str(exc))


class TaskQueue(QObject):
    """Fila de tarefas com paralelismo configurável.

    O número máximo de tarefas simultâneas é controlado pelo usuário
    nas configurações ("Processos simultâneos"), não é fixo.
    """

    task_started = Signal(str)
    task_finished = Signal(str, object)
    task_failed = Signal(str, str)
    task_cancelled = Signal(str)
    task_progress = Signal(str, int)
    all_tasks_finished = Signal()

    def __init__(self, max_concurrent: int = 2) -> None:
        super().__init__()
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(max(1, max_concurrent))
        self._active_tasks: dict[str, _Task] = {}
        self._pending_count = 0

    def set_max_concurrent(self, max_concurrent: int) -> None:
        self._pool.setMaxThreadCount(max(1, max_concurrent))

    def enqueue(self, task_id: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Agenda `func(context, *args, **kwargs)` para rodar em background.

        O primeiro argumento é sempre o `TaskContext` da tarefa, criado
        pela fila — quem enfileira passa só o resto.
        """
        task = _Task(task_id, func, *args, **kwargs)
        task.signals.started.connect(self.task_started)
        task.signals.finished.connect(self._on_task_finished)
        task.signals.failed.connect(self._on_task_failed)
        task.signals.cancelled.connect(self._on_task_cancelled)
        task.signals.progress.connect(self.task_progress)

        self._active_tasks[task_id] = task
        self._pending_count += 1
        self._pool.start(task)

    def cancel(self, task_id: str) -> None:
        """Cancela uma tarefa específica, inclusive a que já está rodando
        (ela para no próximo ponto seguro)."""
        task = self._active_tasks.get(task_id)
        if task:
            task.cancel()

    def cancel_all(self) -> None:
        """Cancela o lote inteiro.

        As tarefas que ainda não começaram nem chegam a rodar; a que já
        está em execução para no próximo ponto seguro do seu próprio
        trabalho. Em qualquer dos casos a fila é drenada, então a
        interface sempre recebe o aviso de que o lote acabou.
        """
        for task in self._active_tasks.values():
            task.cancel()

    def is_idle(self) -> bool:
        return self._pending_count == 0

    def _on_task_finished(self, task_id: str, result: Any) -> None:
        self._drain(task_id)
        self.task_finished.emit(task_id, result)
        self._emit_if_idle()

    def _on_task_failed(self, task_id: str, message: str) -> None:
        self._drain(task_id)
        self.task_failed.emit(task_id, message)
        self._emit_if_idle()

    def _on_task_cancelled(self, task_id: str) -> None:
        self._drain(task_id)
        self.task_cancelled.emit(task_id)
        self._emit_if_idle()

    def _drain(self, task_id: str) -> None:
        """Tira a tarefa da contabilidade da fila, independentemente de
        ela ter terminado, falhado ou sido cancelada."""
        self._active_tasks.pop(task_id, None)
        self._pending_count = max(0, self._pending_count - 1)

    def _emit_if_idle(self) -> None:
        if self._pending_count <= 0:
            self.all_tasks_finished.emit()
