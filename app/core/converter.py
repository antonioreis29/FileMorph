"""
Arquitetura central de conversão.

Este módulo define:

1. `BaseConverter` — a interface que qualquer conversor concreto
   (Pillow, PyMuPDF, FFmpeg, LibreOffice...) deve implementar. A UI e o
   `processor.py` nunca falam diretamente com Pillow/FFmpeg/etc — só
   com essa interface. É isso que garante que o usuário não precise
   saber qual biblioteca está sendo utilizada.

2. `CompatibilityRegistry` — a camada que responde "posso converter
   X para Y?" (`can_convert`). A UI consulta esse registro para nunca
   oferecer uma combinação que não tenha implementação real.

Importante: o registro começa vazio e só passa a responder `True`
quando um conversor real é registrado (por `app/converters/__init__.py`,
na inicialização), evitando qualquer funcionalidade fictícia na
interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.core.task_context import TaskContext
from app.utils.file_utils import refers_to_same_path


@dataclass
class ConversionResult:
    """Resultado de uma conversão individual, usado tanto para sucesso
    quanto para falha: os erros são tratados arquivo por arquivo."""

    success: bool
    input_path: str
    output_path: str | None = None
    error_message: str | None = None


def refuse_overwriting_source(input_path: str, output_path: str) -> ConversionResult | None:
    """Uma falha pronta se o destino é o próprio arquivo de origem; senão None.

    Converter `foto.png` em PNG gravando em `foto.png` leria e escreveria
    o mesmo arquivo — e a gravação atômica terminaria trocando o original
    pelo resultado. O `FileProcessor` já nunca escolhe um destino assim
    (ver `output_planner.py`); esta é a rede de segurança para quem chama
    um conversor diretamente.
    """
    if not refers_to_same_path(input_path, output_path):
        return None
    return ConversionResult(
        success=False,
        input_path=input_path,
        error_message=(
            f"O arquivo convertido não pode substituir o original "
            f"'{Path(input_path).name}'. Escolha outro nome ou outra pasta."
        ),
    )


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
        (e recusar um destino que seja ele — `refuse_overwriting_source`),
        capturar exceções e retornar um ConversionResult com
        `success=False` e uma mensagem amigável em vez de propagar o
        traceback para a UI.

        `context` é o canal com a fila: por ele a conversão
        informa o andamento e descobre que o usuário pediu para parar.
        É opcional porque um conversor também pode ser chamado fora da
        fila — nesse caso não há progresso a reportar nem cancelamento
        possível. Quem trabalha em etapas (páginas, arquivos) deve
        chamar `context.check_cancelled()` entre elas e deixar
        `OperationCancelled` subir: a fila sabe tratá-la.
        """


class CompatibilityRegistry:
    """Registro central de quais conversões são possíveis, e por quem.

    A UI usa `can_convert` para filtrar o seletor de formato e
    `get_converter` para de fato delegar a execução (via processor.py).
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
        pelo seletor de formato para popular as opções."""
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


# Instância única compartilhada pelo aplicativo. Os conversores concretos
# se registram aqui na inicialização (ver `app/converters/__init__.py`).
compatibility_registry = CompatibilityRegistry()
