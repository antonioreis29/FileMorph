"""
Testes do `TaskContext` (Fase 5, itens 16, 17 e 34).

É um módulo pequeno, mas está no caminho de toda conversão: se o
progresso vier errado a barra mente, e se o cancelamento não for visto
o botão "Cancelar" não funciona. Nada aqui depende de Qt.
"""

from __future__ import annotations

import pytest

from app.core.task_context import NULL_CONTEXT, OperationCancelled, TaskContext


def test_null_context_is_inert() -> None:
    """Um conversor chamado fora da fila não tem para quem reportar nem
    como ser cancelado — e isso não pode quebrá-lo."""
    assert not NULL_CONTEXT.cancelled()
    NULL_CONTEXT.check_cancelled()  # não levanta
    NULL_CONTEXT.report(50)  # não faz nada
    NULL_CONTEXT.report_step(1, 2)


def test_report_step_converts_to_percent() -> None:
    reported: list[int] = []
    context = TaskContext(on_progress=reported.append)

    context.report_step(1, 4)
    context.report_step(3, 4)
    context.report_step(40, 40)

    assert reported == [25, 75, 100]


def test_report_step_ignores_empty_work() -> None:
    """Um documento sem páginas não deve gerar uma divisão por zero."""
    reported: list[int] = []
    context = TaskContext(on_progress=reported.append)

    context.report_step(0, 0)

    assert reported == []


def test_percent_is_clamped_to_the_bar_range() -> None:
    reported: list[int] = []
    context = TaskContext(on_progress=reported.append)

    context.report(-10)
    context.report(150)

    assert reported == [0, 100]


def test_check_cancelled_interrupts_only_when_asked() -> None:
    parar = False
    context = TaskContext(is_cancelled=lambda: parar)

    context.check_cancelled()  # ainda não

    parar = True
    assert context.cancelled()
    with pytest.raises(OperationCancelled):
        context.check_cancelled()


def test_cancellation_only_keeps_the_stop_signal_but_drops_progress() -> None:
    """Uma operação que chama outra por dentro (a junção convertendo uma
    imagem) precisa poder ser cancelada, mas o progresso da parte
    interna não pode reescrever o do todo."""
    reported: list[int] = []
    parar = False
    parent = TaskContext(on_progress=reported.append, is_cancelled=lambda: parar)

    child = parent.cancellation_only()
    child.report(100)
    assert reported == []

    parar = True
    with pytest.raises(OperationCancelled):
        child.check_cancelled()
