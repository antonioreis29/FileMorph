"""
Testes dos utilitários de arquivo que protegem a pasta do usuário.

`discard_partial_outputs` é quem limpa a sobra de uma conversão de
várias saídas (as páginas de um PDF, as abas de uma planilha) que falhou
ou foi cancelada no meio. Por mexer em apagar coisas, a regra que mais
importa aqui é a negativa: ela nunca remove uma pasta que não recebeu
explicitamente, e nunca remove uma pasta com conteúdo.
"""

from __future__ import annotations

from pathlib import Path

from app.utils.file_utils import discard_partial_outputs


def test_removes_written_files_and_the_folder_created_for_them(tmp_path: Path) -> None:
    folder = tmp_path / "relatorio"
    folder.mkdir()
    pages = [folder / "relatorio_p01.png", folder / "relatorio_p02.png"]
    for page in pages:
        page.write_bytes(b"pagina")

    discard_partial_outputs(pages, folder)

    assert not folder.exists()
    assert tmp_path.is_dir()


def test_removes_the_created_folder_even_with_nothing_written(tmp_path: Path) -> None:
    """O caso do cancelamento antes da primeira página: não há arquivo
    nenhum de onde deduzir a pasta, e mesmo assim ela precisa sair."""
    folder = tmp_path / "relatorio"
    folder.mkdir()

    discard_partial_outputs([], folder)

    assert not folder.exists()


def test_never_removes_a_folder_it_was_not_given(tmp_path: Path) -> None:
    """Numa saída única o arquivo mora direto na pasta de destino do
    usuário. Ela ficou vazia, mas não foi criada pela conversão."""
    output_dir = tmp_path / "Convertidos"
    output_dir.mkdir()
    single = output_dir / "recibo.png"
    single.write_bytes(b"pagina")

    discard_partial_outputs([single])

    assert not single.exists()
    assert output_dir.is_dir()


def test_keeps_a_created_folder_that_is_not_empty(tmp_path: Path) -> None:
    folder = tmp_path / "relatorio"
    folder.mkdir()
    written = folder / "relatorio_p01.png"
    written.write_bytes(b"pagina")
    foreign = folder / "anotacao.txt"
    foreign.write_text("alguém guardou isto aqui durante a conversão")

    discard_partial_outputs([written], folder)

    assert not written.exists()
    assert foreign.is_file()


def test_tolerates_files_that_are_already_gone(tmp_path: Path) -> None:
    folder = tmp_path / "relatorio"
    folder.mkdir()

    discard_partial_outputs([folder / "nunca_gravado.png"], folder)

    assert not folder.exists()
