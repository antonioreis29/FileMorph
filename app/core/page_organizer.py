"""
Arquitetura central da organização de páginas.

Espelha `converter.py` e `merger.py`, para uma terceira operação: um
documento de várias páginas entra, e o mesmo documento sai com as
páginas em outra ordem.

    relatorio.pdf (1, 2, 3, 4)  ->  relatorio_reorganizado.pdf (3, 1, 4, 2)

Não é uma conversão (o formato não muda) nem uma junção (entra um
arquivo só), e por isso tem interface e registro próprios. A interface
precisa de duas coisas do documento, e as duas passam por aqui para que
ela continue sem saber qual biblioteca está por trás:

- ver as páginas em miniatura enquanto o usuário decide a ordem
  (`BasePageOrganizer.open_preview`);
- gravar o resultado na ordem escolhida (`BasePageOrganizer.reorder`).

As regras da ordem em si — o que é uma ordem válida, como mover
páginas, como descrever a ordem numa linha — também moram aqui, em
funções puras e livres de Qt. A janela e o organizador concreto usam as
mesmas regras, e elas podem ser testadas sem interface nenhuma. A mais
importante é `move_pages`: toda mudança de ordem feita na janela passa
por ela, e ela só devolve permutações — nenhuma página entra duas vezes
nem some, qualquer que seja o arrastar que o usuário fizer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.core.task_context import TaskContext


@dataclass
class PageOrderResult:
    """Resultado de uma reorganização, no mesmo formato de sucesso/falha
    de `ConversionResult`: erros tratados arquivo por arquivo."""

    success: bool
    input_path: str
    output_path: str | None = None
    error_message: str | None = None


class PageOrganizerError(Exception):
    """Problema com o documento, com a mensagem já pronta para o usuário.

    O mesmo papel do `ConversionProblem` dos documentos: interromper lá de
    dentro sem espalhar checagens de retorno pelo caminho.
    """


@dataclass(frozen=True)
class PageThumbnail:
    """A miniatura de uma página, em pixels RGB crus.

    Sem Qt de propósito: quem transforma isto em imagem na tela é a
    interface. `samples` tem 3 bytes por pixel, linha a linha, sem
    preenchimento no fim das linhas.
    """

    width: int
    height: int
    samples: bytes


class PagePreview(ABC):
    """Um documento aberto para mostrar as suas páginas.

    O arquivo fica aberto entre uma miniatura e outra: reabrir um PDF de
    mil páginas para cada miniatura custaria mais do que desenhá-las. Por
    isso precisa ser fechado com `close` (ou usado num `with`).

    Não é seguro para uso simultâneo: quem abre deve usá-lo sempre da
    mesma thread.
    """

    @property
    @abstractmethod
    def page_count(self) -> int:
        """Quantas páginas o documento tem."""

    @abstractmethod
    def render_thumbnail(self, page_index: int, max_side: int) -> PageThumbnail:
        """Desenha a página `page_index` (0 = primeira) com o maior lado
        medindo `max_side` pixels, mantendo a proporção da página."""

    @abstractmethod
    def close(self) -> None:
        """Libera o arquivo."""

    def __enter__(self) -> "PagePreview":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class BasePageOrganizer(ABC):
    """Interface que todo organizador de páginas concreto implementa."""

    @property
    @abstractmethod
    def accepted_formats(self) -> set[str]:
        """Extensões de documento que este organizador sabe reordenar."""

    @abstractmethod
    def open_preview(self, path: str) -> PagePreview:
        """Abre o documento para mostrar as páginas.

        Levanta `PageOrganizerError`, com a mensagem para o usuário,
        quando o arquivo não pode ser organizado: corrompido, protegido,
        sem páginas.
        """

    @abstractmethod
    def reorder(
        self,
        input_path: str,
        output_path: str,
        page_order: Sequence[int],
        context: TaskContext | None = None,
    ) -> PageOrderResult:
        """Grava em `output_path` o documento com as páginas na ordem pedida.

        `page_order[i]` é a página original (0 = primeira) que ocupa a
        posição `i` do documento novo. Implementações devem recusar uma
        ordem que não seja válida (`check_page_order`), nunca alterar o
        arquivo de origem e devolver falha com mensagem amigável
        em vez de propagar exceção — exceto `OperationCancelled`,
        que sobe para a fila tratar.
        """


class PageOrganizerRegistry:
    """Registro central de quais documentos podem ter as páginas
    reorganizadas, e por quem."""

    def __init__(self) -> None:
        self._organizers: list[BasePageOrganizer] = []

    def register(self, organizer: BasePageOrganizer) -> None:
        self._organizers.append(organizer)

    def get_organizer(self, extension: str) -> BasePageOrganizer | None:
        extension = extension.lower().lstrip(".")
        for organizer in self._organizers:
            if extension in organizer.accepted_formats:
                return organizer
        return None

    def can_organize(self, extension: str) -> bool:
        return self.get_organizer(extension) is not None

    def accepted_formats(self) -> set[str]:
        """Todas as extensões com organizador registrado nesta instalação."""
        formats: set[str] = set()
        for organizer in self._organizers:
            formats |= organizer.accepted_formats
        return formats


# Instância única compartilhada pelo aplicativo, preenchida por
# `app/organizers/__init__.py` na inicialização (ver `main.py`).
page_organizer_registry = PageOrganizerRegistry()


# --- Regras da ordem -------------------------------------------------------


def check_page_order(page_order: Sequence[int], page_count: int) -> None:
    """Confere que `page_order` usa cada página do documento exatamente uma vez.

    É a garantia final de que reorganizar não duplica nem perde página. A
    biblioteca de PDF, sozinha, aceitaria as duas coisas sem reclamar —
    repetir e omitir páginas é justamente como ela extrai trechos de um
    documento.
    """
    if len(page_order) != page_count:
        raise PageOrganizerError(
            f"A nova ordem tem {len(page_order)} página(s), mas o documento tem "
            f"{page_count}. Nenhuma página pode ser duplicada ou removida."
        )
    if sorted(page_order) != list(range(page_count)):
        raise PageOrganizerError(
            "A nova ordem repete ou omite páginas do documento. Nenhuma página "
            "pode ser duplicada ou removida."
        )


def is_original_order(page_order: Sequence[int]) -> bool:
    """True se cada página continua na posição em que estava."""
    return all(page == position for position, page in enumerate(page_order))


def move_pages(
    page_order: Sequence[int], positions: Iterable[int], destination: int
) -> tuple[list[int], int]:
    """Move as páginas das `positions` para antes da posição `destination`.

    É o que acontece num arrastar e soltar. `positions` são as posições
    (0 = primeira) das páginas arrastadas, na ordem atual; `destination` é
    onde elas foram soltas — a posição antes da qual entram, contada na
    ordem *atual*, de 0 a `len(page_order)` (o fim). As páginas movidas
    ficam juntas e na mesma ordem relativa em que estavam; todas as outras
    mantêm a ordem entre si.

    Devolve a nova ordem e a posição em que o bloco movido começa, que a
    janela usa para mostrar onde as páginas foram parar.

    Posições fora do documento são ignoradas e o destino é limitado ao
    documento: o resultado é sempre uma permutação da ordem recebida.
    """
    size = len(page_order)
    chosen = sorted({position for position in positions if 0 <= position < size})
    destination = max(0, min(destination, size))
    if not chosen:
        return list(page_order), destination

    chosen_set = set(chosen)
    moved = [page_order[position] for position in chosen]
    kept = [page for position, page in enumerate(page_order) if position not in chosen_set]
    # O destino foi contado com as páginas movidas ainda no lugar; as que
    # estavam antes dele saem da conta.
    start = destination - sum(1 for position in chosen if position < destination)
    return kept[:start] + moved + kept[start:], start


def describe_page_order(page_order: Sequence[int], max_parts: int | None = None) -> str:
    """A ordem em uma linha, na numeração que o usuário vê (a partir de 1).

    Sequências de três ou mais páginas seguidas viram intervalos, para que
    um documento de centenas de páginas caiba numa linha:

        [2, 0, 3, 1]                         ->  "3, 1, 4, 2"
        [49, 0, 1, ..., 48, 50, 51, ..., 99]  ->  "50, 1–49, 51–100"
        [9, 8, 7, ..., 0]                    ->  "10–1"

    `max_parts` corta a descrição depois de tantas partes, terminando em
    reticências — uma ordem embaralhada de mil páginas não tem resumo que
    caiba numa linha.
    """
    numbers = [page + 1 for page in page_order]
    parts: list[str] = []
    index = 0
    while index < len(numbers):
        end = index
        step = 0
        if index + 1 < len(numbers) and abs(numbers[index + 1] - numbers[index]) == 1:
            step = numbers[index + 1] - numbers[index]
            while end + 1 < len(numbers) and numbers[end + 1] - numbers[end] == step:
                end += 1
        if end - index >= 2:
            parts.append(f"{numbers[index]}–{numbers[end]}")
        else:
            end = index
            parts.append(str(numbers[index]))
        index = end + 1

    if max_parts is not None and len(parts) > max_parts:
        return ", ".join(parts[:max_parts]) + ", …"
    return ", ".join(parts)
