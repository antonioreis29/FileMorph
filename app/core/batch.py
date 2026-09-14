"""
O estado de um lote em andamento: que tarefa cuida de quais arquivos.

A interface recebe da fila avisos por tarefa — começou, terminou, falhou,
foi cancelada, está em 40% — e precisa traduzi-los em arquivos da lista.
Numa conversão é fácil, uma tarefa por arquivo. Numa junção não: uma tarefa
só cuida de todos os arquivos da lista, e o id dela não aponta para nenhum
deles. Descobrir o arquivo desmontando o texto do id funcionava para
"convert:<caminho>" e falhava calado para "merge:<destino>" — um cancelamento
ou uma exceção na junção deixava os arquivos parados em "processando" e o
resumo final com a contagem errada.

Aqui a relação é explícita. Cada `PlannedTask` nasce com a lista dos
arquivos que afeta, e o `BatchTracker` guarda essas listas enquanto o lote
roda: qualquer aviso da fila vira atualizações para *todos* os arquivos da
tarefa, e nenhum id precisa ser interpretado.

O acompanhamento é livre de Qt, para poder ser testado sem janela: quem liga
a fila de verdade a ele é `app/ui/batch_controller.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from uuid import uuid4

from app.core.task_context import TaskContext


class FileStatus(str, Enum):
    """A situação de um arquivo da lista durante (e depois de) um lote."""

    WAITING = "waiting"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


# Os tipos de operação, na mesma grafia dos modos da janela.
CONVERT = "convert"
MERGE = "merge"
ORGANIZE = "organize"


def new_task_id(kind: str) -> str:
    """Um id único por tarefa.

    O id identifica a tarefa na fila, e só isso: não carrega caminho nenhum.
    Dois ids com o mesmo texto fariam a fila perder a referência a uma das
    tarefas — o que acontecia ao juntar duas vezes no mesmo destino.
    """
    return f"{kind}:{uuid4().hex}"


@dataclass(frozen=True)
class PlannedTask:
    """Uma tarefa pronta para a fila, com tudo o que a interface precisa saber.

    `affected_paths` são os arquivos da lista que dependem desta tarefa;
    `output_path` é o destino já decidido (ver `output_planner.py`); `run` é
    o trabalho, chamado pela fila com o `TaskContext`.
    """

    task_id: str
    kind: str
    affected_paths: tuple[str, ...]
    output_path: str | None
    run: Callable[[TaskContext], object] = field(repr=False, compare=False)


@dataclass(frozen=True)
class FileUpdate:
    """Uma mudança de situação de um arquivo, para a lista mostrar."""

    path: str
    status: FileStatus
    message: str | None = None


@dataclass(frozen=True)
class BatchSummary:
    """O resultado de um lote que terminou."""

    kind: str
    total_files: int
    succeeded: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]
    stopped: tuple[str, ...]
    cancelled: bool
    # A pasta onde os resultados ficaram: a pasta de saída de uma conversão,
    # ou a pasta do arquivo único de uma junção ou organização.
    output_folder: str
    # O arquivo único de uma junção ou organização; None numa conversão.
    output_path: str | None


_FINAL_STATUSES = (FileStatus.DONE, FileStatus.ERROR, FileStatus.CANCELLED)

_GENERIC_FAILURE = "Não foi possível concluir."


class BatchTracker:
    """Acompanha um lote do começo ao fim.

    Cada método que recebe um aviso da fila devolve as atualizações de
    arquivo que ele provoca. Avisos de uma tarefa que não é deste lote, ou
    que chegam depois de a tarefa já ter terminado, são ignorados — a fila
    é assíncrona, e um aviso atrasado não pode reescrever um resultado.
    """

    def __init__(self, kind: str, tasks: Sequence[PlannedTask], output_dir: str) -> None:
        self.kind = kind
        self._tasks: dict[str, PlannedTask] = {task.task_id: task for task in tasks}
        self._resolved: set[str] = set()
        self._progress: dict[str, int] = {}
        self._status: dict[str, FileStatus] = {}
        self._messages: dict[str, str] = {}
        self._order: list[str] = []
        for task in tasks:
            for path in task.affected_paths:
                if path not in self._status:
                    self._order.append(path)
                self._status[path] = FileStatus.WAITING
        self._output_dir = output_dir
        self._cancel_requested = False

    # --- Leitura -----------------------------------------------------------

    @property
    def total_files(self) -> int:
        return len(self._order)

    @property
    def units(self) -> int:
        """Quantas tarefas o lote tem — a unidade da barra de progresso.

        Converter três arquivos são três tarefas; juntar três arquivos é uma.
        """
        return max(1, len(self._tasks))

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def owns(self, task_id: str) -> bool:
        return task_id in self._tasks

    def affected_paths(self, task_id: str) -> tuple[str, ...]:
        task = self._tasks.get(task_id)
        return task.affected_paths if task is not None else ()

    def status_of(self, path: str) -> FileStatus | None:
        return self._status.get(path)

    def is_finished(self) -> bool:
        return len(self._resolved) == len(self._tasks)

    def initial_updates(self) -> list[FileUpdate]:
        return [FileUpdate(path, FileStatus.WAITING) for path in self._order]

    def current_label(self, task_id: str) -> str | None:
        """O nome a mostrar em "Processando: …" enquanto a tarefa roda.

        Numa junção, o documento que está sendo montado; nas outras
        operações, o arquivo que está sendo lido.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.kind == MERGE and task.output_path:
            return Path(task.output_path).name
        if task.affected_paths:
            return Path(task.affected_paths[0]).name
        return None

    def progress(self) -> tuple[int, int]:
        """(arquivos já finalizados, percentual do lote).

        O percentual soma as tarefas terminadas ao andamento parcial das que
        ainda rodam, para a barra avançar dentro de um arquivo grande e não
        só quando ele termina.
        """
        files_done = sum(1 for status in self._status.values() if status in _FINAL_STATUSES)
        in_flight = sum(self._progress.values())
        percent = round((len(self._resolved) * 100 + in_flight) / self.units)
        return min(files_done, self.total_files), max(0, min(100, percent))

    # --- Avisos da fila ------------------------------------------------------

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def task_started(self, task_id: str) -> list[FileUpdate]:
        if not self._is_open(task_id):
            return []
        return self._set_all(task_id, FileStatus.PROCESSING)

    def task_progress(self, task_id: str, percent: int) -> bool:
        """Guarda o andamento; devolve False para um aviso que não conta."""
        if not self._is_open(task_id):
            return False
        self._progress[task_id] = max(0, min(100, int(percent)))
        return True

    def task_finished(self, task_id: str, result: object) -> list[FileUpdate]:
        """Uma tarefa devolveu resultado — de sucesso ou de falha amigável."""
        if not self._is_open(task_id):
            return []
        self._resolve(task_id)
        if bool(getattr(result, "success", False)):
            return self._set_all(task_id, FileStatus.DONE)
        message = getattr(result, "error_message", None) or _GENERIC_FAILURE
        return self._set_all(task_id, FileStatus.ERROR, message)

    def task_failed(self, task_id: str, message: str) -> list[FileUpdate]:
        """A tarefa levantou exceção: todos os arquivos dela ficam com erro."""
        if not self._is_open(task_id):
            return []
        self._resolve(task_id)
        return self._set_all(task_id, FileStatus.ERROR, message or _GENERIC_FAILURE)

    def task_cancelled(self, task_id: str) -> list[FileUpdate]:
        """A tarefa não chegou a rodar, ou parou no meio a pedido do usuário."""
        if not self._is_open(task_id):
            return []
        self._resolve(task_id)
        return self._set_all(task_id, FileStatus.CANCELLED)

    # --- Resumo ----------------------------------------------------------------

    def summary(self) -> BatchSummary:
        succeeded = tuple(p for p in self._order if self._status[p] == FileStatus.DONE)
        failed = tuple(
            (p, self._messages.get(p, _GENERIC_FAILURE))
            for p in self._order
            if self._status[p] == FileStatus.ERROR
        )
        stopped = tuple(
            p
            for p in self._order
            if self._status[p] in (FileStatus.CANCELLED, FileStatus.WAITING, FileStatus.PROCESSING)
        )
        single_outputs = [
            task.output_path for task in self._tasks.values() if task.kind != CONVERT
        ]
        output_path = single_outputs[0] if len(single_outputs) == 1 else None
        output_folder = str(Path(output_path).parent) if output_path else self._output_dir
        return BatchSummary(
            kind=self.kind,
            total_files=self.total_files,
            succeeded=succeeded,
            failed=failed,
            stopped=stopped,
            cancelled=self._cancel_requested,
            output_folder=output_folder,
            output_path=output_path,
        )

    # --- Interno ----------------------------------------------------------------

    def _is_open(self, task_id: str) -> bool:
        return task_id in self._tasks and task_id not in self._resolved

    def _resolve(self, task_id: str) -> None:
        self._resolved.add(task_id)
        self._progress.pop(task_id, None)

    def _set_all(
        self, task_id: str, status: FileStatus, message: str | None = None
    ) -> list[FileUpdate]:
        updates = []
        for path in self._tasks[task_id].affected_paths:
            self._status[path] = status
            if message is not None:
                self._messages[path] = message
            else:
                self._messages.pop(path, None)
            updates.append(FileUpdate(path, status, message))
        return updates
