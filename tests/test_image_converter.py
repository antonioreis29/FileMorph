"""
Testes do conversor de imagens da Fase 3 (item 34 do briefing).

Diferente de `test_compatibility.py`, que usa dobras de teste, estes
testes exercitam a conversão de verdade: criam imagens pequenas com
Pillow, convertem e verificam o arquivo gerado. São rápidos e não
dependem de nenhum arquivo externo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL", reason="Pillow é a dependência do conversor de imagens")

# Importados depois do `importorskip` porque puxam Pillow junto.
from PIL import Image  # noqa: E402

from app.converters import register_builtin_converters  # noqa: E402
from app.converters.image_converter import ImageConverter  # noqa: E402
from app.core.converter import CompatibilityRegistry  # noqa: E402


def _make_png(path: Path, size: tuple[int, int] = (12, 8), alpha: int = 255) -> Path:
    Image.new("RGBA", size, (200, 30, 60, alpha)).save(path, format="PNG")
    return path


def _make_jpg(path: Path, size: tuple[int, int] = (12, 8)) -> Path:
    Image.new("RGB", size, (10, 120, 200)).save(path, format="JPEG")
    return path


def test_declared_formats_cover_png_jpg_webp() -> None:
    converter = ImageConverter()
    assert {"png", "jpg", "jpeg", "webp"} <= converter.source_formats
    # 'jpeg' nao entra nos destinos: seria uma segunda opcao identica a
    # 'jpg' no seletor de formato.
    assert converter.target_formats == {"png", "jpg", "webp"}


def test_png_to_jpg_flattens_transparency(tmp_path: Path) -> None:
    source = _make_png(tmp_path / "figura.png", alpha=0)
    destination = tmp_path / "figura.jpg"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    assert destination.is_file()
    with Image.open(destination) as image:
        assert image.format == "JPEG"
        # JPEG não tem canal alfa: a área transparente vira o fundo branco.
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_png_to_webp_preserves_size_and_alpha(tmp_path: Path) -> None:
    source = _make_png(tmp_path / "figura.png", size=(20, 5), alpha=128)
    destination = tmp_path / "figura.webp"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert image.format == "WEBP"
        assert image.size == (20, 5)
        assert image.mode == "RGBA"


def test_jpg_to_png_roundtrip(tmp_path: Path) -> None:
    source = _make_jpg(tmp_path / "foto.jpg")
    destination = tmp_path / "foto.png"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    assert result.output_path == str(destination)
    with Image.open(destination) as image:
        assert image.format == "PNG"


def test_jpeg_extension_is_accepted_as_an_alias(tmp_path: Path) -> None:
    """'jpeg' nao aparece no seletor, mas se um destino .jpeg for pedido
    explicitamente a gravacao funciona."""
    source = _make_png(tmp_path / "figura.png")
    destination = tmp_path / "figura.jpeg"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert image.format == "JPEG"


def test_original_file_is_never_modified(tmp_path: Path) -> None:
    source = _make_png(tmp_path / "original.png")
    original_bytes = source.read_bytes()

    ImageConverter().convert(str(source), str(tmp_path / "convertido.jpg"))

    assert source.is_file()
    assert source.read_bytes() == original_bytes


def test_output_directory_is_created_when_missing(tmp_path: Path) -> None:
    source = _make_png(tmp_path / "figura.png")
    destination = tmp_path / "pasta" / "que" / "nao" / "existe" / "figura.webp"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    assert destination.is_file()


def test_corrupted_file_fails_without_raising(tmp_path: Path) -> None:
    fake = tmp_path / "quebrado.png"
    fake.write_bytes(b"isto nao e uma imagem")
    destination = tmp_path / "quebrado.jpg"

    result = ImageConverter().convert(str(fake), str(destination))

    assert not result.success
    assert result.error_message
    # Nenhum arquivo de saída, nem sobra de temporário, é deixado para trás.
    assert not destination.exists()
    assert list(tmp_path.glob("*.filemorph-tmp")) == []
    assert list(tmp_path.glob(".*")) == []


def test_missing_file_fails_with_friendly_message(tmp_path: Path) -> None:
    result = ImageConverter().convert(
        str(tmp_path / "nao_existe.png"), str(tmp_path / "saida.jpg")
    )

    assert not result.success
    assert "não foi encontrado" in (result.error_message or "")


def test_unsupported_target_extension_is_refused(tmp_path: Path) -> None:
    source = _make_png(tmp_path / "figura.png")

    result = ImageConverter().convert(str(source), str(tmp_path / "figura.pdf"))

    assert not result.success
    assert not (tmp_path / "figura.pdf").exists()


def test_existing_output_survives_a_failed_conversion(tmp_path: Path) -> None:
    """A gravação é atômica: uma falha não pode corromper um arquivo bom
    que já ocupava o nome de destino."""
    destination = _make_jpg(tmp_path / "destino.jpg")
    good_bytes = destination.read_bytes()

    broken_source = tmp_path / "quebrado.png"
    broken_source.write_bytes(b"conteudo invalido")

    result = ImageConverter().convert(str(broken_source), str(destination))

    assert not result.success
    assert destination.read_bytes() == good_bytes


def test_register_builtin_converters_populates_registry() -> None:
    registry = CompatibilityRegistry()

    registered = register_builtin_converters(registry)

    assert registered  # com Pillow instalado, o conversor de imagens entra
    assert registry.can_convert("png", "webp")
    assert registry.can_convert("jpeg", "png")
    # Formatos de outras fases continuam indisponíveis, e a interface
    # depende disso para não oferecer conversões inexistentes. (PNG -> PDF
    # passou a existir na Fase 4 e é coberto em test_pdf_converter.py.)
    assert not registry.can_convert("png", "docx")
    assert not registry.can_convert("mp4", "mp3")


def test_register_builtin_converters_is_idempotent() -> None:
    registry = CompatibilityRegistry()

    first = register_builtin_converters(registry)
    second = register_builtin_converters(registry)

    assert first
    assert second == []
    # Uma segunda chamada não pode duplicar conversores nem mudar o que
    # o seletor de formato oferece.
    assert registry.available_targets_for("png") == {"png", "jpg", "webp", "pdf"}
