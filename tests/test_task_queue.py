"""
Testes da fila de tarefas (item 34 do briefing).

Verificam a contabilidade da fila, que é o que garante que a interface
saiba quando o lote acabou — inclusive quando o usuário cancela no
meio. Sem isso, a barra de progresso ficaria presa para sempre.

Desde a Fase 5 verificam também o `TaskContext`: toda tarefa o recebe
como primeiro argumento, e é por ele que uma tarefa longa reporta
andamento e é interrompida no meio.

Os testes rodam sobre um `QCoreApplication` (sem janela), girando o
laço de eventos manualmente, porque os resultados das tarefas chegam
por sinais Qt vindos de outra thread.
"""

from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("PySide6", reason="A fila de tarefas é construída sobre Qt")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.core.task_queue import TaskQueue  # noqa: E402

_TIMEOUT_SECONDS = 5.0


@pytest.fixture(scope="module")
def qt_app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def _spin_until(app: QCoreApplication, condition, timeout: float = _TIMEOUT_SECONDS) -> bool:
    """Gira o laço de eventos até a condição virar verdadeira (ou estourar
    o tempo), para que os sinais das tarefas sejam entregues."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_finished_tasks_report_results_and_drain_the_queue(qt_app: QCoreApplication) -> None:
    queue = TaskQueue(max_concurrent=2)
    results: list[object] = []
    completed: list[bool] = []
    queue.task_finished.connect(lambda _id, result: results.append(result))
    queue.all_tasks_finished.connect(lambda: completed.append(True))

    for index in range(3):
        queue.enqueue(f"task:{index}", lambda _context, value=index: value * 2)

    assert _spin_until(qt_app, lambda: bool(completed))
    assert sorted(results) == [0, 2, 4]  # type: ignore[type-var]
    assert queue.is_idle()


def test_failing_task_does_not_stop_the_queue(qt_app: QCoreApplication) -> None:
    queue = TaskQueue(max_concurrent=1)
    failures: list[str] = []
    completed: list[bool] = []
    queue.task_failed.connect(lambda _id, message: failures.append(message))
    queue.all_tasks_finished.connect(lambda: completed.append(True))

    def explode(_context) -> None:
        raise RuntimeError("falha proposital")

    queue.enqueue("task:boom", explode)
    queue.enqueue("task:ok", lambda _context: "pronto")

    assert _spin_until(qt_app, lambda: bool(completed))
    assert failures == ["falha proposital"]
    assert queue.is_idle()


def test_cancelled_tasks_still_drain_the_queue(qt_app: QCoreApplication) -> None:
    """Uma tarefa cancelada antes de rodar precisa sair da contabilidade,
    senão a interface nunca receberia o aviso de fim de lote."""
    queue = TaskQueue(max_concurrent=1)
    release = threading.Event()
    completed: list[bool] = []
    cancelled: list[str] = []
    queue.task_cancelled.connect(cancelled.append)
    queue.all_tasks_finished.connect(lambda: completed.append(True))

    queue.enqueue("task:lenta", lambda _context: release.wait(_TIMEOUT_SECONDS))
    for index in range(3):
        queue.enqueue(f"task:{index}", lambda _context: "nunca deveria rodar")

    queue.cancel_all()
    release.set()

    assert _spin_until(qt_app, lambda: bool(completed))
    assert queue.is_idle()
    # As três pendentes foram canceladas; a que já estava rodando também
    # tem o resultado descartado, então são quatro cancelamentos.
    assert len(cancelled) == 4


def test_task_reports_progress_through_the_context(qt_app: QCoreApplication) -> None:
    """O contexto é o caminho pelo qual uma tarefa longa conta o quanto
    já fez, sem esperar terminar."""
    queue = TaskQueue(max_concurrent=1)
    reported: list[int] = []
    completed: list[bool] = []
    queue.task_progress.connect(lambda _id, percent: reported.append(percent))
    queue.all_tasks_finished.connect(lambda: completed.append(True))

    def em_etapas(context) -> str:
        for step in range(1, 5):
            context.report_step(step, 4)
        return "pronto"

    queue.enqueue("task:etapas", em_etapas)

    assert _spin_until(qt_app, lambda: bool(completed))
    assert reported == [25, 50, 75, 100]


def test_running_task_stops_at_its_next_safe_point(qt_app: QCoreApplication) -> None:
    """O cancelamento da Fase 5 alcança a tarefa que já está rodando: ela
    enxerga o pedido pelo contexto e para no meio do próprio trabalho."""
    queue = TaskQueue(max_concurrent=1)
    started = threading.Event()
    steps_done: list[int] = []
    cancelled: list[str] = []
    completed: list[bool] = []
    queue.task_cancelled.connect(cancelled.append)
    queue.all_tasks_finished.connect(lambda: completed.append(True))

    def trabalho_longo(context) -> str:
        started.set()
        for step in range(100):
            # Ponto seguro para parar, a cada etapa.
            context.check_cancelled()
            steps_done.append(step)
            time.sleep(0.01)
        return "terminou tudo"

    queue.enqueue("task:longa", trabalho_longo)
    assert started.wait(_TIMEOUT_SECONDS)
    queue.cancel('task:longa')

    assert _spin_until(qt_app, lambda: bool(completed))
    assert cancelled == ["task:longa"]
    # Parou no meio: não chegou nem perto das 100 etapas.
    assert 0 < len(steps_done) < 100
    assert queue.is_idle()
