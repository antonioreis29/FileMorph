"""
Testes da junção de arquivos da Fase 4 (itens 12, 13 e 34 do briefing).

Verificam o que mais importa numa junção: que o resultado tenha todas
as páginas, **na ordem em que o usuário as colocou**, que imagens e
PDFs possam ser misturados, e que os arquivos intermediários da
conversão de imagens não fiquem para trás.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL", reason="Pillow gera as imagens e as páginas")
pytest.importorskip("pypdf", reason="pypdf é a dependência da junção")
pytest.importorskip("pymupdf", reason="PyMuPDF é usado para conferir o resultado")

from PIL import Image  # noqa: E402
import pymupdf  # noqa: E402

from app.core.merger import MergeCompatibilityRegistry  # noqa: E402
from app.mergers import register_builtin_mergers  # noqa: E402
from app.mergers.pdf_merger import PdfMerger  # noqa: E402
from app.utils.temp_manager import temp_manager  # noqa: E402


def _make_pdf(path: Path, pages: int = 1, width: int = 100) -> Path:
    """PDF cujas páginas têm larguras distintas, para os testes poderem
    identificar a ordem no arquivo final."""
    images = [Image.new("RGB", (width, 50), (30, 90, 180)) for _ in range(pages)]
    images[0].save(path, format="PDF", save_all=True, append_images=images[1:])
    return path


def _make_png(path: Path, width: int = 200) -> Path:
    Image.new("RGB", (width, 50), (200, 60, 20)).save(path, format="PNG")
    return path


def _page_widths(path: Path) -> list[int]:
    with pymupdf.open(path) as document:
        return [round(page.rect.width) for page in document]


def test_merges_two_pdfs_in_order(tmp_path: Path) -> None:
    first = _make_pdf(tmp_path / "a.pdf", pages=2, width=100)
    second = _make_pdf(tmp_path / "b.pdf", pages=1, width=300)
    destination = tmp_path / "final.pdf"

    result = PdfMerger().merge([str(first), str(second)], str(destination))

    assert result.success, result.error_message
    assert result.output_path == str(destination)
    assert _page_widths(destination) == [100, 100, 300]


def test_input_order_defines_page_order(tmp_path: Path) -> None:
    """Item 12: a ordem da lista determina a ordem do arquivo final."""
    first = _make_pdf(tmp_path / "a.pdf", width=100)
    second = _make_pdf(tmp_path / "b.pdf", width=300)

    invertido = tmp_path / "invertido.pdf"
    PdfMerger().merge([str(second), str(first)], str(invertido))

    assert _page_widths(invertido) == [300, 100]


def test_merges_images_into_a_single_pdf(tmp_path: Path) -> None:
    imagens = [_make_png(tmp_path / f"foto{i}.png", width=100 + i * 100) for i in range(3)]
    destination = tmp_path / "album.pdf"

    result = PdfMerger().merge([str(p) for p in imagens], str(destination))

    assert result.success, result.error_message
    assert _page_widths(destination) == [100, 200, 300]


def test_mixes_pdfs_and_images(tmp_path: Path) -> None:
    """Item 13: formatos diferentes na mesma junção, via conversão
    intermediária das imagens."""
    pdf = _make_pdf(tmp_path / "contrato.pdf", width=100)
    imagem = _make_png(tmp_path / "anexo.png", width=300)
    destination = tmp_path / "processo.pdf"

    result = PdfMerger().merge([str(pdf), str(imagem), str(pdf)], str(destination))

    assert result.success, result.error_message
    assert _page_widths(destination) == [100, 300, 100]


def test_temporary_files_are_cleaned_up(tmp_path: Path) -> None:
    """Item 24: os PDFs intermediários das imagens não podem ficar
    acumulando na máquina do usuário."""
    imagens = [_make_png(tmp_path / f"foto{i}.png") for i in range(2)]
    temp_root = Path(temp_manager.session_dir("x")).parent
    before = set(temp_root.glob("*")) if temp_root.exists() else set()

    PdfMerger().merge([str(p) for p in imagens], str(tmp_path / "album.pdf"))

    after = set(temp_root.glob("*")) if temp_root.exists() else set()
    assert after == before


def test_sources_are_never_modified(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "original.pdf")
    imagem = _make_png(tmp_path / "foto.png")
    pdf_bytes, imagem_bytes = pdf.read_bytes(), imagem.read_bytes()

    PdfMerger().merge([str(pdf), str(imagem)], str(tmp_path / "final.pdf"))

    assert pdf.read_bytes() == pdf_bytes
    assert imagem.read_bytes() == imagem_bytes


def test_missing_file_fails_before_writing_anything(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "existe.pdf")
    destination = tmp_path / "final.pdf"

    result = PdfMerger().merge([str(pdf), str(tmp_path / "sumiu.pdf")], str(destination))

    assert not result.success
    assert "não encontrado" in (result.error_message or "")
    assert not destination.exists()


def test_corrupted_input_fails_without_partial_output(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "bom.pdf")
    quebrado = tmp_path / "quebrado.pdf"
    quebrado.write_bytes(b"%PDF-1.4 mentira")
    destination = tmp_path / "final.pdf"

    result = PdfMerger().merge([str(pdf), str(quebrado)], str(destination))

    assert not result.success
    assert not destination.exists()
    assert list(tmp_path.glob(".*")) == []


def test_password_protected_pdf_gives_a_clear_message(tmp_path: Path) -> None:
    protegido = tmp_path / "protegido.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(
        protegido,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="dono",
        user_pw="segredo",
    )
    document.close()

    result = PdfMerger().merge(
        [str(_make_pdf(tmp_path / "bom.pdf")), str(protegido)], str(tmp_path / "final.pdf")
    )

    assert not result.success
    assert "senha" in (result.error_message or "")


def test_existing_output_survives_a_failed_merge(tmp_path: Path) -> None:
    destination = _make_pdf(tmp_path / "final.pdf", width=999)
    good_bytes = destination.read_bytes()
    quebrado = tmp_path / "quebrado.pdf"
    quebrado.write_bytes(b"%PDF-1.4 mentira")

    result = PdfMerger().merge([str(quebrado)], str(destination))

    assert not result.success
    assert destination.read_bytes() == good_bytes


def test_registered_merger_answers_the_compatibility_layer() -> None:
    registry = MergeCompatibilityRegistry()

    registered = register_builtin_mergers(registry)

    assert registered
    assert registry.can_merge(["pdf", "pdf"])
    assert registry.can_merge(["png", "jpg", "pdf"])
    assert registry.can_merge(["png", "png"], target_ext="pdf")
    # Formatos de fases futuras continuam sem junção disponível.
    assert not registry.can_merge(["mp3", "mp3"])
    assert not registry.can_merge(["pdf", "docx"])
    assert register_builtin_mergers(registry) == []  # idempotente
