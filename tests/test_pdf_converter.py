"""
Testes dos conversores de PDF.

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

from app.converters import pdf_converter, register_builtin_converters  # noqa: E402
from app.converters.pdf_converter import (  # noqa: E402
    MAX_RENDER_PIXELS,
    PDF_RENDER_DPI,
    ImageToPdfConverter,
    PdfToImageConverter,
    render_zoom,
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


def _make_blank_pdf(path: Path, width: float, height: float) -> Path:
    """PDF de uma página em branco do tamanho pedido, em pontos. Serve às
    páginas fora do comum, que o Pillow não teria como gerar leves."""
    document = pymupdf.open()
    document.new_page(width=width, height=height)
    document.save(path)
    document.close()
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


def test_multipage_tiff_becomes_a_pdf_with_every_page(tmp_path: Path) -> None:
    source = tmp_path / "digitalizacao.tif"
    pages = [Image.new("RGB", (100, 50 + 50 * index), "white") for index in range(3)]
    pages[0].save(source, format="TIFF", save_all=True, append_images=pages[1:])
    destination = tmp_path / "digitalizacao.pdf"

    result = ImageToPdfConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with pymupdf.open(destination) as document:
        assert document.page_count == 3
        assert [round(page.rect.height) for page in document] == [50, 100, 150]


def test_animated_gif_becomes_a_single_page(tmp_path: Path) -> None:
    source = tmp_path / "animacao.gif"
    frames = [Image.new("RGB", (40, 40), color) for color in ("red", "green", "blue")]
    frames[0].save(source, format="GIF", save_all=True, append_images=frames[1:])
    destination = tmp_path / "animacao.pdf"

    result = ImageToPdfConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with pymupdf.open(destination) as document:
        assert document.page_count == 1


@pytest.mark.parametrize("target", ["bmp", "tiff", "gif"])
def test_pdf_to_new_image_formats(tmp_path: Path, target: str) -> None:
    source = _make_pdf(tmp_path / "pagina.pdf")
    destination = tmp_path / f"pagina.{target}"

    result = PdfToImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert image.format == target.upper()


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


def test_failure_on_the_first_page_leaves_no_empty_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A subpasta das páginas é criada antes da primeira página. Uma falha
    logo nela deixava a pasta vazia para trás, porque a limpeza deduzia a
    pasta dos arquivos gravados — e não havia nenhum."""
    source = _make_pdf(tmp_path / "relatorio.pdf", pages=3)
    output_dir = tmp_path / "saida"

    def disco_cheio(*_args, **_kwargs) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(PdfToImageConverter, "_render_page", disco_cheio)

    result = PdfToImageConverter().convert(str(source), str(output_dir / "relatorio.png"))

    assert not result.success
    assert "No space left" in (result.error_message or "")
    assert not (output_dir / "relatorio").exists()
    # A pasta de destino do usuário não é da conversão, e continua lá.
    assert output_dir.is_dir()


# --- Páginas enormes -----------------------------------------------------


def test_normal_pages_keep_the_standard_resolution() -> None:
    assert render_zoom(595, 842, "png") == pytest.approx(PDF_RENDER_DPI / 72)  # A4
    assert render_zoom(595, 842, "webp") == pytest.approx(PDF_RENDER_DPI / 72)


def test_huge_page_fits_the_pixel_ceiling() -> None:
    """200 x 200 polegadas a 150 dpi dariam 900 milhões de pixels."""
    zoom = render_zoom(14400, 14400, "png")

    assert (14400 * zoom) ** 2 <= MAX_RENDER_PIXELS


def test_long_page_fits_the_webp_side_limit() -> None:
    assert 12000 * render_zoom(612, 12000, "webp") < 16383
    # O limite é do WEBP: em PNG a mesma página não perde resolução.
    assert render_zoom(612, 12000, "png") == pytest.approx(PDF_RENDER_DPI / 72)


def test_huge_page_is_downscaled_whole_instead_of_exhausting_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Um teto pequeno faz o teste exercitar a redução sem precisar
    # renderizar dezenas de milhões de pixels de verdade.
    monkeypatch.setattr(pdf_converter, "MAX_RENDER_PIXELS", 40_000)
    source = _make_blank_pdf(tmp_path / "planta.pdf", width=600, height=300)
    destination = tmp_path / "planta.png"

    result = PdfToImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        width, height = image.size
    # Um pixel de folga por lado: o PyMuPDF arredonda o tamanho para cima.
    assert (width - 1) * (height - 1) <= 40_000
    # A página inteira, só que menor: nada foi recortado.
    assert width / height == pytest.approx(2, rel=0.02)


def test_long_page_becomes_a_webp_within_the_format_limit(tmp_path: Path) -> None:
    """72 x 8000 pontos a 150 dpi dariam 16667 px de altura, acima dos
    16383 que o WEBP aceita — o que antes terminava em "erro inesperado"."""
    source = _make_blank_pdf(tmp_path / "extrato.pdf", width=72, height=8000)
    destination = tmp_path / "extrato.webp"

    result = PdfToImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert max(image.size) <= 16383


# --- Registro ------------------------------------------------------------


def test_registry_offers_both_directions() -> None:
    registry = CompatibilityRegistry()

    register_builtin_converters(registry)

    assert registry.can_convert("png", "pdf")
    assert registry.can_convert("jpg", "pdf")
    assert registry.can_convert("pdf", "png")
    images = {"png", "jpg", "webp", "bmp", "tiff", "gif"}
    # O TXT está nesta lista por causa da extração de texto.
    assert registry.available_targets_for("pdf") == images | {"txt"}
    # Imagens agora podem virar PDF, além dos outros formatos de imagem.
    assert registry.available_targets_for("png") == images | {"pdf"}
    assert registry.available_targets_for("tif") == images | {"pdf"}
    # Um PDF e uma imagem juntos só podem ir para o que serve aos dois.
    assert registry.available_targets_for_many({"pdf", "png"}) == images
    # E o que ainda não existe continua não existindo.
    assert not registry.can_convert("pdf", "docx")
    assert not registry.can_convert("mp4", "pdf")
