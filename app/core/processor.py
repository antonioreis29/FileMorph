"""
Orquestrador central de processamento.

`FileProcessor` é a única porta de entrada que a UI usa para converter,
juntar ou organizar arquivos. Ele:

1. Consulta a camada de compatibilidade para confirmar que a operação
   é possível (nunca confia apenas no que a UI já filtrou).
2. **Planeja** o lote antes de executá-lo: decide o destino de cada
   arquivo (`app/core/output_planner.py`) e monta uma `PlannedTask` por
   unidade de trabalho — uma por arquivo numa conversão, uma só numa
   junção ou organização —, já com a lista dos arquivos que ela afeta.
3. Entrega as tarefas à fila e traduz o resultado de cada uma em algo que
   a UI entende (sucesso/erro por arquivo).

Planejar e executar são passos separados (`plan_*` e `submit`) para que a
interface possa registrar o lote antes de a primeira tarefa começar; os
atalhos `convert_batch`, `merge_files` e `organize_pages` fazem os dois de
uma vez.

A fila é recebida por injeção e só precisa cumprir o `TaskQueueProtocol`
(`app/core/task_runner.py`). No aplicativo ela é a `TaskQueue` sobre Qt; nos
testes, uma fila síncrona — e é por isso que este módulo não importa Qt.

Para uma combinação sem conversor registrado — um formato que ainda não
existe, ou que dependa de um programa externo ausente nesta máquina —, a
resposta é um resultado de falha explicando que a operação não existe
nesta instalação, nunca uma conversão simulada.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from app.core.batch import CONVERT, MERGE, ORGANIZE, PlannedTask, new_task_id
from app.core.converter import (
    CompatibilityRegistry,
    ConversionResult,
    compatibility_registry,
)
from app.core.merger import (
    MergeCompatibilityRegistry,
    MergeResult,
    find_input_conflict,
    input_conflict_message,
    merge_compatibility_registry,
)
from app.core.output_planner import find_existing_conflicts, plan_conversion_outputs
from app.core.page_organizer import (
    PageOrderResult,
    PageOrganizerError,
    PageOrganizerRegistry,
    PagePreview,
    page_organizer_registry,
)
from app.core.task_context import TaskContext
from app.core.task_runner import TaskQueueProtocol
from app.utils.file_utils import get_extension, refers_to_same_path
from app.utils.logger import get_logger

logger = get_logger("core.processor")


@dataclass
class BatchRequest:
    input_paths: list[str]
    target_extension: str
    output_dir: str
    overwrite_policy: str = "ask"  # "ask" | "replace" | "copy"


class FileProcessor:
    """Ponto único de orquestração de conversão, junção e organização.

    Os registros são injetáveis para os testes; a aplicação usa os globais,
    preenchidos na inicialização (ver `main.py`).
    """

    def __init__(
        self,
        task_queue: TaskQueueProtocol | None = None,
        *,
        converters: CompatibilityRegistry | None = None,
        mergers: MergeCompatibilityRegistry | None = None,
        organizers: PageOrganizerRegistry | None = None,
    ) -> None:
        self._queue = task_queue
        self._converters = converters if converters is not None else compatibility_registry
        self._mergers = mergers if mergers is not None else merge_compatibility_registry
        self._organizers = organizers if organizers is not None else page_organizer_registry

    # --- Execução -------------------------------------------------------

    def submit(self, tasks: Iterable[PlannedTask]) -> None:
        """Entrega à fila tarefas já planejadas."""
        if self._queue is None:
            raise RuntimeError("Este FileProcessor foi criado sem fila de tarefas.")
        for task in tasks:
            self._queue.enqueue(task.task_id, task.run)

    # --- Conversão em lote ----------------------------------------------

    def can_convert_batch(self, input_paths: list[str], target_extension: str) -> bool:
        return all(
            self._converters.can_convert(get_extension(p), target_extension)
            for p in input_paths
        )

    def available_targets(self, source_extensions: Iterable[str]) -> set[str]:
        """Os destinos que servem a todos os formatos de origem — o que o
        seletor de formato oferece."""
        return self._converters.available_targets_for_many(set(source_extensions))

    def can_convert(self, source_extension: str, target_extension: str) -> bool:
        return self._converters.can_convert(source_extension, target_extension)

    def find_conversion_conflicts(
        self, input_paths: Sequence[str], target_extension: str, output_dir: str
    ) -> list[Path]:
        """Os destinos que já existem e dependem da política de conflito —
        o que a interface precisa perguntar antes de começar."""
        return find_existing_conflicts(input_paths, target_extension, output_dir)

    def plan_conversion(self, request: BatchRequest) -> list[PlannedTask]:
        """Uma tarefa por arquivo, cada uma com o destino já reservado.

        Os destinos de todo o lote são decididos aqui, de uma vez, antes de
        qualquer tarefa rodar: é o que impede dois arquivos de mesmo nome,
        vindos de pastas diferentes e convertidos em paralelo, de gravarem
        um por cima do outro (ver `output_planner.py`).
        """
        planned = plan_conversion_outputs(
            request.input_paths,
            request.target_extension,
            request.output_dir,
            request.overwrite_policy,
        )
        return [
            PlannedTask(
                task_id=new_task_id(CONVERT),
                kind=CONVERT,
                affected_paths=(item.input_path,),
                output_path=str(item.output_path),
                run=partial(
                    self._convert_one,
                    input_path=item.input_path,
                    target_extension=request.target_extension,
                    output_path=str(item.output_path),
                ),
            )
            for item in planned
        ]

    def convert_batch(self, request: BatchRequest) -> list[PlannedTask]:
        """Planeja e enfileira a conversão. Cada arquivo é processado de
        forma independente — se um falhar, os demais continuam."""
        tasks = self.plan_conversion(request)
        self.submit(tasks)
        return tasks

    def _convert_one(
        self,
        context: TaskContext,
        *,
        input_path: str,
        target_extension: str,
        output_path: str,
    ) -> ConversionResult:
        source_ext = get_extension(input_path)
        converter = self._converters.get_converter(source_ext, target_extension)
        if converter is None:
            return ConversionResult(
                success=False,
                input_path=input_path,
                error_message=(
                    f"Não há conversor disponível de .{source_ext} para .{target_extension} "
                    "nesta versão do FileMorph."
                ),
            )
        return converter.convert(input_path, output_path, context)

    # --- Junção -----------------------------------------------------------

    def can_merge(self, input_paths: list[str], target_extension: str | None = None) -> bool:
        exts = [get_extension(p) for p in input_paths]
        return self._mergers.can_merge(exts, target_extension)

    def merge_destination_conflict(self, input_paths: Sequence[str], output_path: str) -> str | None:
        """A entrada que este destino substituiria, ou None. A interface usa
        para pedir outro nome antes de começar."""
        return find_input_conflict(input_paths, output_path)

    def plan_merge(
        self, input_paths: list[str], output_path: str, target_extension: str | None = None
    ) -> PlannedTask:
        """Uma única tarefa, respeitando a ordem de `input_paths`."""
        paths = list(input_paths)
        return PlannedTask(
            task_id=new_task_id(MERGE),
            kind=MERGE,
            affected_paths=tuple(paths),
            output_path=output_path,
            run=partial(
                self._merge_one,
                input_paths=paths,
                output_path=output_path,
                target_extension=target_extension,
            ),
        )

    def merge_files(
        self, input_paths: list[str], output_path: str, target_extension: str | None = None
    ) -> PlannedTask:
        task = self.plan_merge(input_paths, output_path, target_extension)
        self.submit([task])
        return task

    def _merge_one(
        self,
        context: TaskContext,
        *,
        input_paths: list[str],
        output_path: str,
        target_extension: str | None,
    ) -> MergeResult:
        # A proteção das entradas vale aqui, antes de escolher o merger, e
        # não só na janela: nenhum caminho até a gravação pode depender de
        # a interface ter perguntado.
        conflict = find_input_conflict(input_paths, output_path)
        if conflict is not None:
            logger.warning("Junção recusada: o destino %s é uma das entradas", output_path)
            return MergeResult(
                success=False,
                input_paths=list(input_paths),
                error_message=input_conflict_message(conflict),
            )

        exts = [get_extension(p) for p in input_paths]
        merger = self._mergers.get_merger(exts, target_extension)
        if merger is None:
            return MergeResult(
                success=False,
                input_paths=list(input_paths),
                error_message="Não há junção disponível para esta combinação de formatos nesta versão do FileMorph.",
            )
        return merger.merge(list(input_paths), output_path, context)

    # --- Organização de páginas -----------------------------------------

    def can_organize_pages(self, input_paths: list[str]) -> bool:
        """Organizar é sobre um documento só: a operação existe para
        exatamente um arquivo, de um formato com organizador registrado."""
        return len(input_paths) == 1 and self._organizers.can_organize(
            get_extension(input_paths[0])
        )

    def organizable_formats(self) -> set[str]:
        """Os formatos que podem ter as páginas organizadas nesta instalação,
        para a interface explicar o que a operação espera."""
        return self._organizers.accepted_formats()

    def open_page_preview(self, input_path: str) -> PagePreview:
        """Abre o documento para a janela de organização mostrar as páginas.

        Não passa pela fila: quem chama é a própria janela, da thread que
        desenha as miniaturas. Levanta `PageOrganizerError`, com a mensagem
        pronta, quando não há como organizar este arquivo.
        """
        extension = get_extension(input_path)
        organizer = self._organizers.get_organizer(extension)
        if organizer is None:
            raise PageOrganizerError(self._no_organizer_message(extension))
        return organizer.open_preview(input_path)

    def plan_organize(
        self, input_path: str, output_path: str, page_order: Sequence[int]
    ) -> PlannedTask:
        return PlannedTask(
            task_id=new_task_id(ORGANIZE),
            kind=ORGANIZE,
            affected_paths=(input_path,),
            output_path=output_path,
            run=partial(
                self._organize_one,
                input_path=input_path,
                output_path=output_path,
                page_order=list(page_order),
            ),
        )

    def organize_pages(
        self, input_path: str, output_path: str, page_order: Sequence[int]
    ) -> PlannedTask:
        """Planeja e enfileira a gravação do documento com a nova ordem."""
        task = self.plan_organize(input_path, output_path, page_order)
        self.submit([task])
        return task

    def _organize_one(
        self,
        context: TaskContext,
        *,
        input_path: str,
        output_path: str,
        page_order: list[int],
    ) -> PageOrderResult:
        if refers_to_same_path(input_path, output_path):
            return PageOrderResult(
                success=False,
                input_path=input_path,
                error_message=(
                    "Escolha outro nome para o arquivo reorganizado: o FileMorph "
                    "nunca altera o arquivo original."
                ),
            )
        extension = get_extension(input_path)
        organizer = self._organizers.get_organizer(extension)
        if organizer is None:
            return PageOrderResult(
                success=False,
                input_path=input_path,
                error_message=self._no_organizer_message(extension),
            )
        return organizer.reorder(input_path, output_path, page_order, context)

    @staticmethod
    def _no_organizer_message(extension: str) -> str:
        return (
            f"Não há como organizar as páginas de um arquivo .{extension} "
            "nesta versão do FileMorph."
        )
