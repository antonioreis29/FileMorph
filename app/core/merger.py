"""
Arquitetura central de junção de arquivos (itens 12, 13 e 14 do briefing).

Espelha `converter.py`, mas para a operação "Juntar": vários arquivos
de entrada (possivelmente de formatos diferentes, via pipeline de
conversão intermediária — item 13) resultam em um único arquivo de
saída.

O primeiro merger concreto chegou na Fase 4
(`app/mergers/pdf_merger.py`, que une PDFs e imagens em um único PDF).
Para as combinações sem merger registrado, o modo "Juntar" continua
informando honestamente que a operação não existe nesta versão.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.task_context import TaskContext


@dataclass
class MergeResult:
    success: bool
    input_paths: list[str]
    output_path: str | None = None
    error_message: str | None = None


class BaseMerger(ABC):
    """Interface que todo merger concreto deve implementar."""

    @property
    @abstractmethod
    def accepted_formats(self) -> set[str]:
        """Extensões que este merger aceita como entrada (ex.: {'pdf'},
        ou {'jpg', 'png', 'webp'} para o merger de imagens -> PDF)."""

    @property
    @abstractmethod
    def output_format(self) -> str:
        """Extensão única de saída produzida por este merger (ex.: 'pdf')."""

    @abstractmethod
    def merge(
        self,
        input_paths: list[str],
        output_path: str,
        context: TaskContext | None = None,
    ) -> MergeResult:
        """Executa a junção, respeitando a ordem de `input_paths` (item 12:
        "a ordem da lista deve determinar a ordem do arquivo final").

        `context` (Fase 5) é o canal com a fila, igual ao dos
        conversores: por ele a junção reporta o andamento (arquivo 3 de
        10) e verifica, entre um arquivo e outro, se o usuário mandou
        parar."""


class MergeCompatibilityRegistry:
    """Registro central de quais junções são possíveis, e por quem."""

    def __init__(self) -> None:
        self._mergers: list[BaseMerger] = []

    def register(self, merger: BaseMerger) -> None:
        self._mergers.append(merger)

    def can_merge(self, source_exts: list[str], target_ext: str | None = None) -> bool:
        """Verifica se um conjunto de extensões de entrada pode ser unido.

        Se `target_ext` for informado, exige que o merger produza
        exatamente esse formato de saída (útil quando há mais de um
        merger compatível com os mesmos formatos de entrada).
        """
        exts = {e.lower().lstrip(".") for e in source_exts}
        if not exts:
            return False
        for merger in self._mergers:
            if exts.issubset(merger.accepted_formats):
                if target_ext is None or merger.output_format == target_ext.lower().lstrip("."):
                    return True
        return False

    def get_merger(self, source_exts: list[str], target_ext: str | None = None) -> BaseMerger | None:
        exts = {e.lower().lstrip(".") for e in source_exts}
        for merger in self._mergers:
            if exts.issubset(merger.accepted_formats):
                if target_ext is None or merger.output_format == target_ext.lower().lstrip("."):
                    return merger
        return None


# Instância única compartilhada pelo aplicativo. Mergers concretos
# (Fase 4 em diante) se registram aqui na inicialização do app.
merge_compatibility_registry = MergeCompatibilityRegistry()
