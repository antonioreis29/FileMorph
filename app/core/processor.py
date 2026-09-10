"""
Orquestrador central de processamento (item 10/11/15 do briefing).

`FileProcessor` é a única porta de entrada que a UI usa para
converter ou juntar arquivos. Ele:

1. Consulta a camada de compatibilidade para confirmar que a operação
   é possível (nunca confia apenas no que a UI já filtrou).
2. Monta uma tarefa por arquivo (conversão) ou uma tarefa única
   (junção) e as enfileira na `TaskQueue`.
3. Traduz o resultado de cada tarefa em algo que a UI entende
   (sucesso/erro por arquivo — item 22).

A partir da Fase 3 este módulo executa conversões de verdade: a Fase 4
acrescentou o PDF e a primeira junção real, e a Fase 6 trouxe áudio e
vídeo via FFmpeg. Para as famílias de formato ainda não implementadas
(documentos, planilhas), a resposta continua sendo um resultado de
falha explicando que a operação não existe nesta versão — nunca uma
conversão simulada.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.converter import ConversionResult, compatibility_registry
from app.core.merger import MergeResult, merge_compatibility_registry
from app.core.task_context import TaskContext
from app.core.task_queue import TaskQueue
from app.utils.file_utils import (
    ensure_directory,
    get_extension,
    get_stem,
    get_unique_path,
    resolve_output_path,
)
from app.utils.logger import get_logger

logger = get_logger("core.processor")


@dataclass
class BatchRequest:
    input_paths: list[str]
    target_extension: str
    output_dir: str
    overwrite_policy: str = "ask"  # "ask" | "replace" | "copy"


class FileProcessor:
    """Ponto único de orquestração de conversão/junção de arquivos."""

    def __init__(self, task_queue: TaskQueue) -> None:
        self._queue = task_queue

    # --- Conversão em lote (itens 10/11) -------------------------------

    def can_convert_batch(self, input_paths: list[str], target_extension: str) -> bool:
        return all(
            compatibility_registry.can_convert(get_extension(p), target_extension)
            for p in input_paths
        )

    def convert_batch(self, request: BatchRequest) -> None:
        """Enfileira uma tarefa de conversão por arquivo. Cada arquivo é
        processado de forma independente — se um falhar, os demais
        continuam (item 11)."""
        for input_path in request.input_paths:
            task_id = f"convert:{input_path}"
            self._queue.enqueue(
                task_id,
                self._convert_one,
                input_path,
                request.target_extension,
                request.output_dir,
                request.overwrite_policy,
            )

    def _convert_one(
        self,
        context: TaskContext,
        input_path: str,
        target_extension: str,
        output_dir: str,
        overwrite_policy: str,
    ) -> ConversionResult:
        source_ext = get_extension(input_path)
        converter = compatibility_registry.get_converter(source_ext, target_extension)
        if converter is None:
            return ConversionResult(
                success=False,
                input_path=input_path,
                error_message=(
                    f"Não há conversor disponível de .{source_ext} para .{target_extension} "
                    "nesta versão do FileMorph."
                ),
            )

        ensure_directory(output_dir)
        output_path = resolve_output_path(output_dir, get_stem(input_path), target_extension)

        # Converter um arquivo "para ele mesmo" (ex.: foto.png -> PNG na
        # mesma pasta) leria e gravaria o mesmo caminho, destruindo o
        # original. Nesse caso o resultado sempre vira uma cópia nova,
        # independentemente da política escolhida (item 18).
        if output_path.resolve() == Path(input_path).resolve():
            output_path = get_unique_path(output_path)
        elif output_path.exists() and overwrite_policy in ("copy", "ask"):
            # "ask" só chega aqui se a interface não tiver resolvido o
            # conflito antes; nesse caso o padrão seguro é preservar o
            # arquivo existente em vez de substituí-lo (item 21).
            output_path = get_unique_path(output_path)

        return converter.convert(input_path, str(output_path), context)

    # --- Junção (itens 12/13) -------------------------------------------

    def can_merge(self, input_paths: list[str], target_extension: str | None = None) -> bool:
        exts = [get_extension(p) for p in input_paths]
        return merge_compatibility_registry.can_merge(exts, target_extension)

    def merge_files(
        self, input_paths: list[str], output_path: str, target_extension: str | None = None
    ) -> None:
        """Enfileira uma única tarefa de junção, respeitando a ordem de
        `input_paths` (item 12)."""
        task_id = f"merge:{output_path}"
        self._queue.enqueue(task_id, self._merge_one, input_paths, output_path, target_extension)

    def _merge_one(
        self,
        context: TaskContext,
        input_paths: list[str],
        output_path: str,
        target_extension: str | None,
    ) -> MergeResult:
        exts = [get_extension(p) for p in input_paths]
        merger = merge_compatibility_registry.get_merger(exts, target_extension)
        if merger is None:
            return MergeResult(
                success=False,
                input_paths=input_paths,
                error_message="Não há junção disponível para esta combinação de formatos nesta versão do FileMorph.",
            )
        return merger.merge(input_paths, output_path, context)
