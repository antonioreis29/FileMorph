"""
Canal de mão dupla entre uma tarefa e a fila.

Sem este canal, uma conversão seria uma caixa-preta: começa, termina, e
no meio disso a interface não sabe de nada nem tem como pedir para
parar. O progresso avançaria de arquivo em arquivo, e cancelar só
impediria que as tarefas *seguintes* começassem.

`TaskContext` resolve os dois lados com um objeto só, entregue pela
fila a cada tarefa:

- **para fora**: `report_step` avisa o quanto já foi feito dentro da
  tarefa (página 3 de 40), e a interface soma isso ao progresso geral;
- **para dentro**: `check_cancelled` pergunta se o usuário mandou parar,
  e interrompe a operação levantando `OperationCancelled`.

O cancelamento é cooperativo: quem faz o trabalho decide *onde* é
seguro parar (entre uma página e outra, entre um arquivo e outro), de
modo que nunca se interrompe uma gravação pela metade.

Este módulo é deliberadamente livre de Qt. Os conversores e mergers
dependem dele, e nada em `app/converters` ou `app/mergers` deve
precisar de PySide6 para rodar (ou para ser testado).
"""

from __future__ import annotations

from collections.abc import Callable


class OperationCancelled(Exception):
    """Levantada de dentro de uma tarefa quando o usuário cancelou.

    Não é um erro: a fila a reconhece e trata a tarefa como cancelada,
    sem mostrar mensagem de falha para o usuário.
    """


class TaskContext:
    """O contexto que toda tarefa recebe como primeiro argumento.

    Fora da fila (em testes, ou numa chamada direta a um conversor) o
    contexto padrão não faz nada: não há para quem reportar e não há
    cancelamento possível. É por isso que `context` é sempre opcional
    na assinatura dos conversores.
    """

    def __init__(
        self,
        on_progress: Callable[[int], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self._on_progress = on_progress
        self._is_cancelled = is_cancelled

    # --- Cancelamento -----------------------------------------------------

    def cancelled(self) -> bool:
        """True se o usuário já pediu para parar."""
        return bool(self._is_cancelled and self._is_cancelled())

    def check_cancelled(self) -> None:
        """Interrompe a tarefa se o cancelamento já foi pedido.

        Deve ser chamado em pontos seguros do trabalho — entre páginas,
        entre arquivos —, nunca no meio de uma gravação.
        """
        if self.cancelled():
            raise OperationCancelled()

    # --- Progresso --------------------------------------------------------

    def report(self, percent: int) -> None:
        """Informa o andamento da tarefa, de 0 a 100."""
        if self._on_progress is None:
            return
        self._on_progress(max(0, min(100, int(percent))))

    def report_step(self, done: int, total: int) -> None:
        """Versão conveniente para trabalho contável ('página 3 de 40')."""
        if total <= 0:
            return
        self.report(round(done * 100 / total))

    # --- Derivação --------------------------------------------------------

    def cancellation_only(self) -> "TaskContext":
        """Um contexto que ainda pode ser cancelado, mas cujo progresso é
        ignorado.

        Serve para quando uma operação chama outra por dentro: a junção
        de PDFs converte cada imagem antes de concatenar, e o progresso
        dessa conversão interna não pode reescrever o progresso da
        junção como um todo.
        """
        return TaskContext(on_progress=None, is_cancelled=self._is_cancelled)


# Contexto neutro para quem chama um conversor fora da fila.
NULL_CONTEXT = TaskContext()
