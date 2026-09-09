"""
Arquitetura central de conversão (itens 4, 10 e 14 do briefing).

Este módulo define:

1. `BaseConverter` — a interface que qualquer conversor concreto
   (Pillow, pypdf, FFmpeg, LibreOffice...) deve implementar. A UI e o
   `processor.py` nunca falam diretamente com Pillow/FFmpeg/etc — só
   com essa interface. É isso que garante o princípio fundamental do
   item 4: "o usuário não deve precisar saber qual biblioteca está
   sendo utilizada".

2. `CompatibilityRegistry` — a camada que responde "posso converter
   X para Y?" (`can_convert`). A UI consulta esse registro para nunca
   oferecer uma combinação que não tenha implementação real (item 14).

Importante: o registro começa vazio e só passa a responder `True`
quando um conversor real é implementado e registrado (por
`app/converters/__init__.py`, na inicialização), evitando qualquer
funcionalidade fictícia na interface (item 37).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.core.task_context import TaskContext


@dataclass
class ConversionResult:
    """Resultado de uma conversão individual, usado tanto para sucesso
    quanto para falha (item 22: erros tratados por arquivo)."""

    success: bool
    input_path: str
    output_path: str | None = None
    error_message: str | None = None


class BaseConverter(ABC):
    """Interface que todo conversor concreto deve implementar.

    Cada conversor é responsável por UMA família de formato de origem
    (ex.: imagens), e sabe quais formatos de destino consegue gerar.
    """

    @property
    @abstractmethod
    def source_formats(self) -> set[str]:
        """Extensões de entrada suportadas por este conversor, em minúsculas
        e sem ponto (ex.: {'png', 'jpg', 'webp'})."""

    @property
    @abstractmethod
    def target_formats(self) -> set[str]:
        """Extensões de saída que este conversor consegue produzir."""

    @abstractmethod
    def convert(
        self, input_path: str, output_path: str, context: TaskContext | None = None
    ) -> ConversionResult:
        """Executa a conversão de um único arquivo.

        Implementações devem: nunca modificar/apagar o arquivo original
        (item 18), capturar exceções e retornar um ConversionResult com
        `success=False` e uma mensagem amigável em vez de propagar o
        traceback para a UI (item 22).

        `context` (Fase 5) é o canal com a fila: por ele a conversão
        informa o andamento e descobre que o usuário pediu para parar.
        É opcional porque um conversor também pode ser chamado fora da
        fila — nesse caso não há progresso a reportar nem cancelamento
        possível. Quem trabalha em etapas (páginas, arquivos) deve
        chamar `context.check_cancelled()` entre elas e deixar
        `OperationCancelled` subir: a fila sabe tratá-la.
        """


class CompatibilityRegistry:
    """Registro central de quais conversões são possíveis, e por quem.

    A UI usa `can_convert` para filtrar o seletor de formato (item 10)
    e `get_converter` para de fato delegar a execução (via processor.py).
    """

    def __init__(self) -> None:
        self._converters: list[BaseConverter] = []

    def register(self, converter: BaseConverter) -> None:
        self._converters.append(converter)

    def can_convert(self, source_ext: str, target_ext: str) -> bool:
        source_ext = source_ext.lower().lstrip(".")
        target_ext = target_ext.lower().lstrip(".")
        return any(
            source_ext in c.source_formats and target_ext in c.target_formats
            for c in self._converters
        )

    def get_converter(self, source_ext: str, target_ext: str) -> BaseConverter | None:
        source_ext = source_ext.lower().lstrip(".")
        target_ext = target_ext.lower().lstrip(".")
        for converter in self._converters:
            if source_ext in converter.source_formats and target_ext in converter.target_formats:
                return converter
        return None

    def available_targets_for(self, source_ext: str) -> set[str]:
        """Todos os formatos de destino possíveis para uma extensão de
        origem, considerando todos os conversores registrados. Usado
        pelo seletor de formato para popular as opções (item 10)."""
        source_ext = source_ext.lower().lstrip(".")
        targets: set[str] = set()
        for converter in self._converters:
            if source_ext in converter.source_formats:
                targets |= converter.target_formats
        return targets

    def available_targets_for_many(self, source_exts: set[str]) -> set[str]:
        """Interseção dos formatos de destino possíveis para um conjunto
        de arquivos de origens diferentes — usado em conversão em lote
        com tipos mistos, para só oferecer um destino que sirva para
        todos os arquivos selecionados."""
        if not source_exts:
            return set()
        result: set[str] | None = None
        for ext in source_exts:
            targets = self.available_targets_for(ext)
            result = targets if result is None else (result & targets)
        return result or set()


def resolve_output_extension(target_ext: str) -> str:
    return target_ext.lower().lstrip(".")


# Instância única compartilhada pelo aplicativo. Conversores concretos
# (Fases 3+) se registram aqui na inicialização do app.
compatibility_registry = CompatibilityRegistry()
