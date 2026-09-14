"""
Planejamento dos arquivos de saída de um lote, antes de qualquer tarefa rodar.

A conversão em lote roda em paralelo. Se cada tarefa escolhesse o próprio
destino na hora de gravar — "`foto.webp` existe? não? então é meu" —, duas
tarefas poderiam fazer a pergunta ao mesmo tempo, receber a mesma resposta
e gravar uma por cima da outra:

    C:\\A\\foto.jpg  ->  Convertidos\\foto.webp
    C:\\B\\foto.png  ->  Convertidos\\foto.webp   (o mesmo nome)

Por isso os destinos são decididos aqui, **de uma vez e na thread que monta
o lote**, antes de a primeira tarefa começar. Cada destino escolhido fica
reservado para o resto do lote, e cada tarefa recebe o caminho já pronto:
nenhuma thread decide nome nenhum, então não há disputa possível entre elas.

As regras de um destino, na ordem em que valem:

1. **Um arquivo de entrada do próprio lote nunca é destino.** Nem o arquivo
   que está sendo convertido (`foto.png` para PNG na mesma pasta), nem outro
   arquivo da lista que por acaso tenha o nome de saída de alguém. Nesses
   casos o resultado sempre vira uma cópia numerada, qualquer que seja a
   política escolhida — substituir uma entrada destruiria o original.
2. **Um nome já reservado por outro arquivo do lote nunca é reaproveitado.**
   O segundo `foto.webp` vira `foto (1).webp`, o terceiro `foto (2).webp`.
   Isso vale inclusive com a política "substituir": ela autoriza trocar um
   arquivo que *já existia* antes do lote, nunca o resultado de outro
   arquivo do mesmo lote.
3. **Um arquivo que já existe no disco** é substituído com a política
   "replace" e preservado (o resultado vira cópia numerada) com "copy" e
   "ask". "ask" só chega até aqui se a interface não resolveu o conflito
   antes, e o padrão seguro é não destruir nada. Uma *pasta* com o nome do
   destino nunca é substituída.

Os nomes são comparados como o Windows os compara (ver
`app.utils.file_utils.path_key`): `FOTO.webp` e `foto.WEBP` são o mesmo
arquivo, e reservá-los como se fossem dois deixaria as duas tarefas
gravando no mesmo lugar.

Este módulo não cria nada no disco e não depende de Qt.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.utils.file_utils import get_stem, path_key, resolve_output_path

# As políticas de conflito aceitas, na mesma grafia usada pela interface.
OVERWRITE_POLICIES: tuple[str, ...] = ("ask", "replace", "copy")


@dataclass(frozen=True)
class PlannedOutput:
    """O destino decidido para um arquivo do lote."""

    input_path: str
    output_path: Path
    # True quando o destino é um arquivo que já existia e vai ser
    # substituído (política "replace").
    replaces_existing: bool = False


class OutputPlanner:
    """Reserva destinos para um lote, sem deixar dois arquivos com o mesmo.

    `protected_paths` são os caminhos que nunca podem virar destino — na
    prática, todos os arquivos de entrada do lote.
    """

    def __init__(self, protected_paths: Iterable[str | Path] = ()) -> None:
        self._protected: set[str] = {path_key(path) for path in protected_paths}
        self._reserved: set[str] = set()

    def claim(self, input_path: str | Path, desired: str | Path, policy: str) -> PlannedOutput:
        """Decide e reserva o destino de um arquivo.

        `desired` é o caminho que o arquivo teria sem conflito nenhum. As
        regras estão no cabeçalho deste módulo.
        """
        if policy not in OVERWRITE_POLICIES:
            raise ValueError(f"Política de conflito desconhecida: {policy!r}")

        desired = Path(desired)
        key = path_key(desired)
        replaces = False

        if key in self._protected or key in self._reserved:
            chosen = self._free_variant(desired)
        elif desired.exists() or desired.is_symlink():
            if policy == "replace" and desired.is_file():
                chosen, replaces = desired, True
            else:
                chosen = self._free_variant(desired)
        else:
            chosen = desired

        self._reserved.add(path_key(chosen))
        return PlannedOutput(str(input_path), chosen, replaces)

    def _free_variant(self, desired: Path) -> Path:
        """`nome (1).ext`, `nome (2).ext`... o primeiro que não é entrada do
        lote, não foi reservado e não existe no disco."""
        stem, suffix, parent = desired.stem, desired.suffix, desired.parent
        counter = 1
        while True:
            candidate = parent / f"{stem} ({counter}){suffix}"
            key = path_key(candidate)
            if (
                key not in self._protected
                and key not in self._reserved
                and not candidate.exists()
                and not candidate.is_symlink()
            ):
                return candidate
            counter += 1


def plan_conversion_outputs(
    input_paths: Sequence[str],
    target_extension: str,
    output_dir: str | Path,
    policy: str,
) -> list[PlannedOutput]:
    """Os destinos de uma conversão em lote, na ordem dos arquivos.

    Cada arquivo mantém o próprio nome com a extensão nova, dentro de
    `output_dir`, e os conflitos são resolvidos pelas regras do cabeçalho.
    """
    planner = OutputPlanner(protected_paths=input_paths)
    return [
        planner.claim(
            path, resolve_output_path(output_dir, get_stem(path), target_extension), policy
        )
        for path in input_paths
    ]


def find_existing_conflicts(
    input_paths: Sequence[str], target_extension: str, output_dir: str | Path
) -> list[Path]:
    """Os destinos que já existem no disco e que a política decide se
    substitui ou preserva — é o que a interface pergunta ao usuário.

    Um destino que é arquivo de entrada do lote não entra na lista: ele
    nunca é substituído, qualquer que seja a resposta, então perguntar
    seria oferecer uma escolha que não existe. Um nome repetido dentro do
    próprio lote também não entra, pelo mesmo motivo — ele sempre vira
    cópia numerada.
    """
    protected = {path_key(path) for path in input_paths}
    seen: set[str] = set()
    conflicts: list[Path] = []
    for path in input_paths:
        desired = resolve_output_path(output_dir, get_stem(path), target_extension)
        key = path_key(desired)
        if key in protected or key in seen:
            continue
        seen.add(key)
        if desired.exists():
            conflicts.append(desired)
    return conflicts
