"""
Testes do planejamento de destinos de um lote (`app/core/output_planner.py`).

O que está sendo protegido: dois arquivos do mesmo lote nunca recebem o
mesmo destino, nenhum destino é um arquivo de entrada, e a política de
conflito ("replace", "copy", "ask") só decide sobre arquivos que já
existiam antes do lote. Tudo aqui é decidido sem gravar nada — os testes
conferem só os caminhos escolhidos.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.core.output_planner import (
    OutputPlanner,
    find_existing_conflicts,
    plan_conversion_outputs,
)


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _names(planned) -> list[str]:
    return [item.output_path.name for item in planned]


def test_same_stem_from_two_folders_gets_two_destinations(tmp_path: Path) -> None:
    a = _touch(tmp_path / "A" / "foto.jpg")
    b = _touch(tmp_path / "B" / "foto.jpg")

    planned = plan_conversion_outputs([str(a), str(b)], "webp", tmp_path / "saida", "copy")

    assert _names(planned) == ["foto.webp", "foto (1).webp"]


def test_different_source_extensions_with_the_same_stem(tmp_path: Path) -> None:
    a = _touch(tmp_path / "A" / "foto.jpg")
    b = _touch(tmp_path / "B" / "foto.png")

    planned = plan_conversion_outputs([str(a), str(b)], "webp", tmp_path / "saida", "replace")

    assert _names(planned) == ["foto.webp", "foto (1).webp"]


def test_three_or_more_collisions_are_numbered_in_order(tmp_path: Path) -> None:
    sources = [_touch(tmp_path / f"pasta{i}" / "foto.png") for i in range(5)]

    planned = plan_conversion_outputs([str(s) for s in sources], "jpg", tmp_path / "saida", "ask")

    assert _names(planned) == [
        "foto.jpg",
        "foto (1).jpg",
        "foto (2).jpg",
        "foto (3).jpg",
        "foto (4).jpg",
    ]
    assert len({item.output_path for item in planned}) == 5


def test_copy_policy_skips_existing_files(tmp_path: Path) -> None:
    saida = tmp_path / "saida"
    _touch(saida / "foto.webp")
    _touch(saida / "foto (1).webp")
    source = _touch(tmp_path / "A" / "foto.jpg")

    planned = plan_conversion_outputs([str(source)], "webp", saida, "copy")

    assert _names(planned) == ["foto (2).webp"]
    assert not planned[0].replaces_existing


def test_ask_policy_behaves_like_copy(tmp_path: Path) -> None:
    """'ask' só chega ao planejamento se a interface não resolveu o
    conflito; o padrão seguro é preservar o que existe."""
    saida = tmp_path / "saida"
    _touch(saida / "foto.webp")
    source = _touch(tmp_path / "A" / "foto.jpg")

    planned = plan_conversion_outputs([str(source)], "webp", saida, "ask")

    assert _names(planned) == ["foto (1).webp"]


def test_replace_policy_replaces_a_file_that_already_existed(tmp_path: Path) -> None:
    saida = tmp_path / "saida"
    existing = _touch(saida / "foto.webp")
    source = _touch(tmp_path / "A" / "foto.jpg")

    planned = plan_conversion_outputs([str(source)], "webp", saida, "replace")

    assert planned[0].output_path == existing
    assert planned[0].replaces_existing


def test_replace_never_reuses_a_name_reserved_in_the_same_batch(tmp_path: Path) -> None:
    """"Substituir" autoriza trocar o arquivo antigo — nunca o resultado de
    outro arquivo do mesmo lote."""
    saida = tmp_path / "saida"
    _touch(saida / "foto.webp")
    a = _touch(tmp_path / "A" / "foto.jpg")
    b = _touch(tmp_path / "B" / "foto.jpg")

    planned = plan_conversion_outputs([str(a), str(b)], "webp", saida, "replace")

    assert _names(planned) == ["foto.webp", "foto (1).webp"]
    assert [item.replaces_existing for item in planned] == [True, False]


def test_a_source_file_is_never_a_destination(tmp_path: Path) -> None:
    """PNG para PNG na mesma pasta: o original não pode ser o destino, nem
    com a política de substituir."""
    source = _touch(tmp_path / "imagem.png")

    planned = plan_conversion_outputs([str(source)], "png", tmp_path, "replace")

    assert _names(planned) == ["imagem (1).png"]


def test_another_input_of_the_batch_is_never_replaced(tmp_path: Path) -> None:
    """`foto.png` para JPG na mesma pasta cairia em `foto.jpg` — que é outro
    arquivo da lista, e seria destruído com "substituir"."""
    png = _touch(tmp_path / "foto.png")
    jpg = _touch(tmp_path / "foto.jpg", b"entrada que precisa sobreviver")

    planned = plan_conversion_outputs([str(png), str(jpg)], "jpg", tmp_path, "replace")

    outputs = {item.output_path for item in planned}
    assert jpg not in outputs
    assert _names(planned) == ["foto (1).jpg", "foto (2).jpg"]


def test_a_folder_with_the_destination_name_is_never_replaced(tmp_path: Path) -> None:
    saida = tmp_path / "saida"
    (saida / "foto.webp").mkdir(parents=True)
    source = _touch(tmp_path / "A" / "foto.jpg")

    planned = plan_conversion_outputs([str(source)], "webp", saida, "replace")

    assert _names(planned) == ["foto (1).webp"]


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="nomes sem distinção de maiúsculas são do Windows")
def test_names_differing_only_in_case_are_the_same_destination(tmp_path: Path) -> None:
    a = _touch(tmp_path / "A" / "Foto.jpg")
    b = _touch(tmp_path / "B" / "FOTO.png")

    planned = plan_conversion_outputs([str(a), str(b)], "webp", tmp_path / "saida", "replace")

    assert [n.lower() for n in _names(planned)] == ["foto.webp", "foto (1).webp"]


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="nomes sem distinção de maiúsculas são do Windows")
def test_existing_file_in_other_case_counts_as_existing(tmp_path: Path) -> None:
    saida = tmp_path / "saida"
    _touch(saida / "FOTO.WEBP", b"arquivo antigo")
    source = _touch(tmp_path / "A" / "foto.jpg")

    planned = plan_conversion_outputs([str(source)], "webp", saida, "copy")

    assert _names(planned) == ["foto (1).webp"]


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="nomes sem distinção de maiúsculas são do Windows")
def test_source_in_other_case_is_still_protected(tmp_path: Path) -> None:
    source = _touch(tmp_path / "Imagem.PNG")

    planner = OutputPlanner(protected_paths=[str(source)])
    planned = planner.claim(str(source), tmp_path / "imagem.png", "replace")

    assert planned.output_path.name == "imagem (1).png"


def test_unicode_names_and_folders_with_spaces(tmp_path: Path) -> None:
    a = _touch(tmp_path / "Minhas Fotos" / "férias à beira-mar.jpg")
    b = _touch(tmp_path / "Outra pasta" / "férias à beira-mar.png")

    planned = plan_conversion_outputs([str(a), str(b)], "webp", tmp_path / "Saída Final", "copy")

    assert _names(planned) == ["férias à beira-mar.webp", "férias à beira-mar (1).webp"]
    assert all(item.output_path.parent == tmp_path / "Saída Final" for item in planned)


def test_unknown_policy_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        OutputPlanner().claim("a.png", tmp_path / "a.jpg", "sobrescrever")


def test_conflicts_to_ask_about_list_each_preexisting_file_once(tmp_path: Path) -> None:
    """Dois arquivos do lote que cairiam no mesmo nome existente geram uma
    pergunta só: o segundo sempre vira cópia numerada."""
    saida = tmp_path / "saida"
    existing = _touch(saida / "foto.webp")
    a = _touch(tmp_path / "A" / "foto.jpg")
    b = _touch(tmp_path / "B" / "foto.png")

    assert find_existing_conflicts([str(a), str(b)], "webp", saida) == [existing]


def test_an_input_of_the_batch_is_not_a_conflict_to_ask_about(tmp_path: Path) -> None:
    """Uma entrada do lote nunca é substituída, qualquer que seja a resposta
    — perguntar seria oferecer uma escolha que não existe."""
    png = _touch(tmp_path / "foto.png")
    jpg = _touch(tmp_path / "foto.jpg")

    assert find_existing_conflicts([str(png), str(jpg)], "jpg", tmp_path) == []
