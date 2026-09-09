"""
Testes de progresso e cancelamento dentro das operações reais
(Fase 5 — itens 16, 17 e 34).

Aqui não se testa a fila em si (isso é `test_task_queue.py`), e sim o
lado de dentro: um PDF de muitas páginas realmente avisa o quanto já
converteu? Cancelar no meio para de verdade — e, o mais importante,
sem deixar arquivo pela metade na pasta do usuário?
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL", reason="Pillow gera as imagens de teste")
pytest.importorskip("pymupdf", reason="PyMuPDF converte PDF em imagens")
pytest.importorskip("pypdf", reason="pypdf faz a junção")

from PIL import Image  # noqa: E402

from app.converters.image_converter import ImageConverter  # noqa: E402
from app.converters.pdf_converter import PdfToImageConverter  # noqa: E402
from app.core.task_context import OperationCancelled, TaskContext  # noqa: E402
from app.mergers.pdf_merger import PdfMerger  # noqa: E402
from app.utils.temp_manager import temp_manager  # noqa: E402


def _make_png(path: Path) -> Path:
    Image.new("RGB", (60, 40), (10, 160, 90)).save(path, format="PNG")
    return path


def _make_pdf(path: Path, pages: int) -> Path:
    images = [Image.new("RGB", (80, 60), (30, 90, 180)) for _ in range(pages)]
    images[0].save(path, format="PDF", save_all=True, append_images=images[1:])
    return path


class _Recorder:
    """Contexto de teste: guarda o progresso e pode mandar parar depois de
    um número escolhido de avisos."""

    def __init__(self, cancel_after: int | None = None) -> None:
        self.reported: list[int] = []
        self._cancel_after = cancel_after
        self.context = TaskContext(
            on_progress=self.reported.append,
            is_cancelled=lambda: (
                self._cancel_after is not None and len(self.reported) >= self._cancel_after
            ),
        )


# --- Progresso -----------------------------------------------------------


def test_pdf_conversion_reports_page_by_page(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "livro.pdf", pages=5)
    recorder = _Recorder()

    result = PdfToImageConverter().convert(
        str(source), str(tmp_path / "saida" / "livro.png"), recorder.context
    )

    assert result.success, result.error_message
    assert recorder.reported == [20, 40, 60, 80, 100]


def test_merge_reports_progress_across_its_two_halves(tmp_path: Path) -> None:
    """A junção reporta enquanto prepara as entradas e enquanto concatena,
    terminando em 100."""
    entradas = [str(_make_pdf(tmp_path / f"doc{i}.pdf", pages=1)) for i in range(3)]
    recorder = _Recorder()

    result = PdfMerger().merge(entradas, str(tmp_path / "final.pdf"), recorder.context)

    assert result.success, result.error_message
    assert recorder.reported == sorted(recorder.reported)  # nunca anda para trás
    assert recorder.reported[-1] == 100


def test_image_conversion_reports_completion(tmp_path: Path) -> None:
    source = _make_png(tmp_path / "foto.png")
    recorder = _Recorder()

    result = ImageConverter().convert(str(source), str(tmp_path / "foto.jpg"), recorder.context)

    assert result.success, result.error_message
    assert recorder.reported == [100]


# --- Cancelamento --------------------------------------------------------


def test_cancelling_a_pdf_conversion_leaves_no_half_written_pages(tmp_path: Path) -> None:
    """Interromper no meio não pode deixar páginas soltas — nem a subpasta
    vazia — na pasta de saída (itens 17 e 24)."""
    source = _make_pdf(tmp_path / "livro.pdf", pages=6)
    output_dir = tmp_path / "saida"
    recorder = _Recorder(cancel_after=2)  # para depois de duas páginas

    with pytest.raises(OperationCancelled):
        PdfToImageConverter().convert(
            str(source), str(output_dir / "livro.png"), recorder.context
        )

    assert list(output_dir.rglob("*.png")) == []
    assert not (output_dir / "livro").exists()


def test_cancelling_a_merge_leaves_no_output_and_no_temp_files(tmp_path: Path) -> None:
    entradas = [str(_make_png(tmp_path / f"foto{i}.png")) for i in range(4)]
    destination = tmp_path / "album.pdf"
    temp_root = Path(temp_manager.session_dir("x")).parent
    before = set(temp_root.glob("*")) if temp_root.exists() else set()
    recorder = _Recorder(cancel_after=1)

    with pytest.raises(OperationCancelled):
        PdfMerger().merge(entradas, str(destination), recorder.context)

    assert not destination.exists()
    assert list(tmp_path.glob(".*")) == []  # nenhum temporário de gravação
    after = set(temp_root.glob("*")) if temp_root.exists() else set()
    assert after == before  # nenhum intermediário deixado para trás


def test_cancelling_a_merge_preserves_an_existing_output(tmp_path: Path) -> None:
    """Cancelar não pode destruir um arquivo bom que já ocupava o nome de
    destino: a gravação só acontece no fim, sobre um temporário."""
    destination = _make_pdf(tmp_path / "final.pdf", pages=1)
    original = destination.read_bytes()
    entradas = [str(_make_pdf(tmp_path / f"doc{i}.pdf", pages=1)) for i in range(3)]
    recorder = _Recorder(cancel_after=1)

    with pytest.raises(OperationCancelled):
        PdfMerger().merge(entradas, str(destination), recorder.context)

    assert destination.read_bytes() == original


def test_cancelling_before_an_image_conversion_writes_nothing(tmp_path: Path) -> None:
    source = _make_png(tmp_path / "foto.png")
    destination = tmp_path / "foto.jpg"
    always_cancelled = TaskContext(is_cancelled=lambda: True)

    with pytest.raises(OperationCancelled):
        ImageConverter().convert(str(source), str(destination), always_cancelled)

    assert not destination.exists()
    assert source.is_file()  # o original segue intacto
