"""
Testes dos conversores de PDF da Fase 4 (item 34 do briefing).

Como no teste do conversor de imagens, aqui a conversão acontece de
verdade: os PDFs são gerados na hora com Pillow e relidos com PyMuPDF.
Nada depende de arquivos externos.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL", reason="Pillow é usado para gerar as páginas")
pytest.importorskip("pymupdf", reason="PyMuPDF é a dependência de PDF -> imagens")

from PIL import Image  # noqa: E402
import pymupdf  # noqa: E402

from app.converters import register_builtin_converters  # noqa: E402
from app.converters.pdf_converter import (  # noqa: E402
    ImageToPdfConverter,
    PdfToImageConverter,
)
from app.core.converter import CompatibilityRegistry  # noqa: E402


def _make_png(path: Path, size: tuple[int, int] = (60, 40), alpha: int = 255) -> Path:
    Image.new("RGBA", size, (10, 160, 90, alpha)).save(path, format="PNG")
    return path


def _make_pdf(path: Path, pages: int = 1) -> Path:
    """Gera um PDF com o número de páginas pedido, cada uma de uma cor."""
    images = [
        Image.new("RGB", (120, 80), (40 * (index + 1) % 256, 80, 200)) for index in range(pages)
    ]
    images[0].save(path, format="PDF", save_all=True, append_images=images[1:])
    return path


# --- Imagens -> PDF ------------------------------------------------------


def test_image_to_pdf_creates_single_page_document(tmp_path: Path) -> None:
    source = _make_png(tmp_path / "foto.png")
    destination = tmp_path / "foto.pdf"

    result = ImageToPdfConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with pymupdf.open(destination) as document:
        assert document.page_count == 1


def test_image_to_pdf_page_matches_image_size(tmp_path: Path) -> None:
    """Sem DPI declarado, a página fica do tamanho exato da imagem em
    pontos — nada é recortado nem redimensionado."""
    source = _make_png(tmp_path / "foto.png", size=(300, 150))
    destination = tmp_path / "foto.pdf"

    ImageToPdfConverter().convert(str(source), str(destination))

    with pymupdf.open(destination) as document:
        page = document[0]
        assert round(page.rect.width) == 300
        assert round(page.rect.height) == 150


def test_image_to_pdf_accepts_transparency(tmp_path: Path) -> None:
    """PDF não guarda transparência de página: a imagem é achatada em
    vez de a conversão falhar."""
    source = _make_png(tmp_path / "recorte.png", alpha=0)
    destination = tmp_path / "recorte.pdf"

    result = ImageToPdfConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    assert destination.is_file()


def test_image_to_pdf_rejects_corrupted_input(tmp_path: Path) -> None:
    broken = tmp_path / "quebrado.png"
    broken.write_bytes(b"nao sou imagem")

    result = ImageToPdfConverter().convert(str(broken), str(tmp_path / "saida.pdf"))

    assert not result.success
    assert not (tmp_path / "saida.pdf").exists()
    assert list(tmp_path.glob(".*")) == []


# --- PDF -> imagens ------------------------------------------------------


def test_single_page_pdf_becomes_the_requested_file(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "recibo.pdf")
    destination = tmp_path / "recibo.png"

    result = PdfToImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    assert result.output_path == str(destination)
    with Image.open(destination) as image:
        assert image.format == "PNG"
        # 150 dpi sobre uma página de 120x80 pontos (72 dpi).
        assert image.size == (250, 167)


def test_multi_page_pdf_goes_into_its_own_folder(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "relatorio.pdf", pages=3)
    output_dir = tmp_path / "saida"

    result = PdfToImageConverter().convert(str(source), str(output_dir / "relatorio.jpg"))

    assert result.success, result.error_message
    folder = output_dir / "relatorio"
    assert result.output_path == str(folder)
    assert sorted(p.name for p in folder.iterdir()) == [
        "relatorio_p01.jpg",
        "relatorio_p02.jpg",
        "relatorio_p03.jpg",
    ]


def test_second_run_never_overwrites_the_previous_folder(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "relatorio.pdf", pages=2)
    destination = tmp_path / "saida" / "relatorio.png"

    first = PdfToImageConverter().convert(str(source), str(destination))
    second = PdfToImageConverter().convert(str(source), str(destination))

    assert first.success and second.success
    assert first.output_path != second.output_path
    assert Path(second.output_path or "").name == "relatorio (1)"


def test_pdf_to_webp_is_supported(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "pagina.pdf")
    destination = tmp_path / "pagina.webp"

    result = PdfToImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert image.format == "WEBP"


def test_password_protected_pdf_gives_a_clear_message(tmp_path: Path) -> None:
    source = tmp_path / "protegido.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(
        source,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="dono",
        user_pw="segredo",
    )
    document.close()

    result = PdfToImageConverter().convert(str(source), str(tmp_path / "protegido.png"))

    assert not result.success
    assert "senha" in (result.error_message or "")


def test_corrupted_pdf_fails_without_raising(tmp_path: Path) -> None:
    broken = tmp_path / "quebrado.pdf"
    broken.write_bytes(b"%PDF-1.4 mentira")

    result = PdfToImageConverter().convert(str(broken), str(tmp_path / "quebrado.png"))

    assert not result.success
    assert result.error_message
    assert not (tmp_path / "quebrado.png").exists()


def test_pdf_source_never_changes(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "original.pdf", pages=2)
    original_bytes = source.read_bytes()

    PdfToImageConverter().convert(str(source), str(tmp_path / "saida" / "original.png"))

    assert source.read_bytes() == original_bytes


def test_unsupported_target_is_refused(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "doc.pdf")

    result = PdfToImageConverter().convert(str(source), str(tmp_path / "doc.docx"))

    assert not result.success
    assert not (tmp_path / "doc.docx").exists()


# --- Registro ------------------------------------------------------------


def test_registry_offers_both_directions() -> None:
    registry = CompatibilityRegistry()

    register_builtin_converters(registry)

    assert registry.can_convert("png", "pdf")
    assert registry.can_convert("jpg", "pdf")
    assert registry.can_convert("pdf", "png")
    # O TXT entrou nesta lista na Fase 7, junto com a extração de texto.
    assert registry.available_targets_for("pdf") == {"png", "jpg", "webp", "txt"}
    # Imagens agora podem virar PDF, além dos outros formatos de imagem.
    assert registry.available_targets_for("png") == {"png", "jpg", "webp", "pdf"}
    # Um PDF e uma imagem juntos só podem ir para o que serve aos dois.
    assert registry.available_targets_for_many({"pdf", "png"}) == {"png", "jpg", "webp"}
    # E o que ainda não existe continua não existindo.
    assert not registry.can_convert("pdf", "docx")
    assert not registry.can_convert("mp4", "pdf")
