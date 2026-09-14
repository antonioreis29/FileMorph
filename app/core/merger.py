"""
Arquitetura central de junção de arquivos.

Espelha `converter.py`, mas para a operação "Juntar": vários arquivos
de entrada (possivelmente de formatos diferentes, via conversão
intermediária) resultam em um único arquivo de saída.

O merger concreto é `app/mergers/pdf_merger.py`, que une PDFs, imagens
e documentos em um único PDF. Para as combinações sem merger
registrado, o modo "Juntar" informa honestamente que a operação não
existe nesta instalação.

**O destino nunca pode ser uma das entradas.** Juntar `a.pdf` e `b.pdf`
salvando como `a.pdf` terminaria substituindo o original pelo resultado.
A regra mora aqui (`find_input_conflict`) para valer em qualquer caminho
até a gravação — a janela pergunta antes, o `FileProcessor` confere de
novo e o próprio merger recusa —, sem depender de a interface ter
lembrado de perguntar.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.core.task_context import TaskContext
from app.utils.file_utils import refers_to_same_path


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
        """Executa a junção, respeitando a ordem de `input_paths`: a ordem
        da lista é a ordem do arquivo final.

        `context` é o canal com a fila, igual ao dos conversores: por ele a
        junção reporta o andamento (arquivo 3 de 10) e verifica, entre um
        arquivo e outro, se o usuário mandou parar.

        Implementações devem recusar um `output_path` que seja uma das
        entradas (`find_input_conflict`)."""


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


def find_input_conflict(input_paths: Sequence[str], output_path: str) -> str | None:
    """A entrada que o destino substituiria, ou None se o destino é livre.

    Compara com todas as entradas, e do jeito que o Windows compara nomes
    (`refers_to_same_path`): `C:\\Docs\\A.pdf` e `c:/docs/a.PDF` são o
    mesmo arquivo.
    """
    for path in input_paths:
        if refers_to_same_path(path, output_path):
            return path
    return None


def input_conflict_message(conflicting_input: str) -> str:
    """A explicação para o usuário quando o destino é uma das entradas."""
    return (
        f"O arquivo final não pode ter o mesmo nome de '{Path(conflicting_input).name}', "
        "que é um dos arquivos sendo juntados — ele seria substituído. Escolha "
        "outro nome para o arquivo final. Nenhum arquivo foi alterado."
    )


# Instância única compartilhada pelo aplicativo. Os mergers concretos se
# registram aqui na inicialização (ver `app/mergers/__init__.py`).
merge_compatibility_registry = MergeCompatibilityRegistry()
