"""
Testes do conversor de imagens.

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
from PIL import ExifTags, Image, ImageCms  # noqa: E402

from app.converters import register_builtin_converters  # noqa: E402
from app.converters.image_converter import ImageConverter  # noqa: E402
from app.core.converter import CompatibilityRegistry  # noqa: E402


def _make_png(path: Path, size: tuple[int, int] = (12, 8), alpha: int = 255) -> Path:
    Image.new("RGBA", size, (200, 30, 60, alpha)).save(path, format="PNG")
    return path


def _make_jpg(path: Path, size: tuple[int, int] = (12, 8)) -> Path:
    Image.new("RGB", size, (10, 120, 200)).save(path, format="JPEG")
    return path


def test_declared_formats() -> None:
    converter = ImageConverter()
    assert {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "gif"} <= converter.source_formats
    # 'jpeg' e 'tif' nao entram nos destinos: seriam segundas opcoes
    # identicas a 'jpg' e 'tiff' no seletor de formato.
    assert converter.target_formats == {"png", "jpg", "webp", "bmp", "tiff", "gif"}


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


def test_refuses_to_write_over_the_source(tmp_path: Path) -> None:
    """Chamado direto (sem o planejamento do processador), o conversor ainda
    recusa um destino que é a própria origem."""
    source = _make_png(tmp_path / "figura.png")
    original_bytes = source.read_bytes()

    result = ImageConverter().convert(str(source), str(tmp_path / "FIGURA.png"))

    assert not result.success
    assert source.read_bytes() == original_bytes
    assert [p.name for p in tmp_path.iterdir()] == ["figura.png"]


# --- Orientação EXIF ---------------------------------------------------------------

_ORIENTATION = ExifTags.Base.Orientation


def _make_rotated_photo(path: Path, with_icc: bool = True) -> Path:
    """Uma "foto de celular": pixels deitados (40x20) e a tag dizendo que a
    imagem deve ser girada 90° (Orientation = 6), com câmera, data e GPS."""
    exif = Image.Exif()
    exif[_ORIENTATION] = 6
    exif[ExifTags.Base.Make] = "Camera de Teste"
    exif[ExifTags.Base.Model] = "Modelo X"
    exif[ExifTags.Base.DateTime] = "2024:05:06 07:08:09"
    exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = "2024:05:06 07:08:09"
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "S"
    gps[ExifTags.GPS.GPSLatitude] = (23.0, 32.0, 51.0)
    options = {"exif": exif.tobytes()}
    if with_icc:
        options["icc_profile"] = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.new("RGB", (40, 20), (200, 30, 60)).save(path, format="JPEG", **options)
    return path


@pytest.mark.parametrize("target", ["jpg", "webp"])
def test_exif_orientation_is_applied_once(tmp_path: Path, target: str) -> None:
    """Os pixels são girados, e a tag de orientação sai do arquivo novo.

    Se a tag ficasse, a imagem já de pé seria girada de novo por qualquer
    visualizador que respeita o EXIF — a foto apareceria deitada.
    """
    source = _make_rotated_photo(tmp_path / "celular.jpg")
    destination = tmp_path / f"convertida.{target}"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert image.size == (20, 40)
        exif = image.getexif()
        assert exif.get(_ORIENTATION, 1) == 1
        # O resto do EXIF continua sendo o da foto.
        assert exif.get(ExifTags.Base.Make) == "Camera de Teste"
        assert exif.get(ExifTags.Base.Model) == "Modelo X"
        assert exif.get(ExifTags.Base.DateTime) == "2024:05:06 07:08:09"
        assert (
            exif.get_ifd(ExifTags.IFD.Exif).get(ExifTags.Base.DateTimeOriginal)
            == "2024:05:06 07:08:09"
        )
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        assert gps.get(ExifTags.GPS.GPSLatitudeRef) == "S"
        assert tuple(float(v) for v in gps.get(ExifTags.GPS.GPSLatitude)) == (23.0, 32.0, 51.0)
        assert image.info.get("icc_profile")


def test_orientation_from_the_source_is_never_copied_back(tmp_path: Path) -> None:
    """Conferência direta das opções de gravação: a origem ainda tem a tag,
    as opções que saem para o arquivo novo não."""
    from app.converters.image_converter import save_options

    source = _make_rotated_photo(tmp_path / "celular.jpg")
    with Image.open(source) as image:
        assert image.getexif().get(_ORIENTATION) == 6
        options = save_options(image, "jpg")

    written = Image.Exif()
    written.load(options["exif"])
    assert _ORIENTATION not in written
    assert written.get(ExifTags.Base.Make) == "Camera de Teste"


def test_icc_profile_is_dropped_when_the_color_space_changes(tmp_path: Path) -> None:
    """Um perfil de CMYK não descreve um PNG que virou RGB."""
    source = tmp_path / "grafica.jpg"
    Image.new("CMYK", (10, 10), (0, 50, 100, 0)).save(
        source, format="JPEG", icc_profile=b"perfil CMYK de mentira"
    )
    destination = tmp_path / "grafica.png"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert image.mode == "RGB"
        assert not image.info.get("icc_profile")


def test_register_builtin_converters_populates_registry() -> None:
    registry = CompatibilityRegistry()

    registered = register_builtin_converters(registry)

    assert registered  # com Pillow instalado, o conversor de imagens entra
    assert registry.can_convert("png", "webp")
    assert registry.can_convert("jpeg", "png")
    # Formatos sem conversor continuam indisponíveis, e a interface
    # depende disso para não oferecer conversões inexistentes. (PNG -> PDF
    # é coberto em test_pdf_converter.py.)
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
    assert registry.available_targets_for("png") == {
        "png", "jpg", "webp", "bmp", "tiff", "gif", "pdf"
    }


# --- BMP, TIFF e GIF -----------------------------------------------------------------


@pytest.mark.parametrize("source_format, ext", [("BMP", "bmp"), ("TIFF", "tif"), ("GIF", "gif")])
@pytest.mark.parametrize("target", ["png", "jpg", "webp", "bmp", "tiff", "gif"])
def test_new_formats_convert_in_every_direction(
    tmp_path: Path, source_format: str, ext: str, target: str
) -> None:
    source = tmp_path / f"figura.{ext}"
    Image.new("RGB", (30, 20), (10, 120, 200)).save(source, format=source_format)
    destination = tmp_path / "saida" / f"figura.{target}"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert image.format == {"jpg": "JPEG"}.get(target, target.upper())
        assert image.size == (30, 20)


def test_tif_extension_is_accepted_as_an_alias(tmp_path: Path) -> None:
    source = _make_png(tmp_path / "figura.png")
    destination = tmp_path / "figura.tif"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert image.format == "TIFF"


def test_png_to_bmp_flattens_transparency_onto_white(tmp_path: Path) -> None:
    """O BMP aceita RGBA e descarta o alfa em silêncio: sem achatar, a área
    transparente mostraria a cor escondida por baixo dela."""
    source = _make_png(tmp_path / "recorte.png", alpha=0)
    destination = tmp_path / "recorte.bmp"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_png_to_gif_turns_partial_transparency_into_all_or_nothing(tmp_path: Path) -> None:
    source = tmp_path / "logo.png"
    image = Image.new("RGBA", (3, 1), (0, 0, 0, 0))
    image.putpixel((0, 0), (0, 0, 0, 40))  # sombra quase transparente
    image.putpixel((1, 0), (255, 0, 0, 255))
    image.putpixel((2, 0), (255, 0, 0, 128))
    image.save(source, format="PNG")
    destination = tmp_path / "logo.gif"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as gif:
        pixels = [gif.convert("RGBA").getpixel((x, 0)) for x in range(3)]
    # A sombra some em vez de virar um pixel preto sólido.
    assert pixels[0][3] == 0
    assert pixels[1] == (255, 0, 0, 255)
    # Meio transparente: opaco, mas composto sobre o branco.
    assert pixels[2][3] == 255
    assert pixels[2][1] > 100


def test_tiff_output_is_compressed_without_loss(tmp_path: Path) -> None:
    source = tmp_path / "foto.png"
    Image.new("RGB", (200, 200), (10, 120, 200)).save(source, format="PNG")
    destination = tmp_path / "foto.tiff"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert image.info.get("compression") == "tiff_lzw"
        assert image.getpixel((5, 5)) == (10, 120, 200)
    assert destination.stat().st_size < 200 * 200 * 3


def test_rotated_photo_becomes_an_upright_tiff(tmp_path: Path) -> None:
    source = _make_rotated_photo(tmp_path / "celular.jpg")
    destination = tmp_path / "convertida.tiff"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert image.size == (20, 40)
        assert image.getexif().get(_ORIENTATION, 1) == 1
        assert image.info.get("icc_profile")


def _make_multipage_tiff(path: Path, pages: int = 3) -> Path:
    images = [Image.new("RGB", (40, 20 + 10 * index), (40 * index, 80, 200)) for index in range(pages)]
    images[0].save(path, format="TIFF", save_all=True, append_images=images[1:])
    return path


def _make_animated_gif(path: Path, frames: int = 3) -> Path:
    images = [Image.new("RGB", (16, 16), (80 * index, 30, 200)) for index in range(frames)]
    images[0].save(path, format="GIF", save_all=True, append_images=images[1:], duration=120, loop=0)
    return path


def test_multipage_tiff_to_image_goes_into_its_own_folder(tmp_path: Path) -> None:
    """Como um PDF de várias páginas: nenhuma página é perdida em silêncio."""
    source = _make_multipage_tiff(tmp_path / "digitalizacao.tif")
    output_dir = tmp_path / "saida"

    result = ImageConverter().convert(str(source), str(output_dir / "digitalizacao.png"))

    assert result.success, result.error_message
    folder = output_dir / "digitalizacao"
    assert result.output_path == str(folder)
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["digitalizacao_p01.png", "digitalizacao_p02.png", "digitalizacao_p03.png"]
    with Image.open(folder / "digitalizacao_p03.png") as image:
        assert image.size == (40, 40)


def test_multipage_tiff_to_tiff_keeps_every_page_in_one_file(tmp_path: Path) -> None:
    source = _make_multipage_tiff(tmp_path / "digitalizacao.tif")
    destination = tmp_path / "saida" / "digitalizacao.tiff"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    assert result.output_path == str(destination)
    with Image.open(destination) as image:
        assert image.n_frames == 3


def test_cancelling_a_multipage_tiff_leaves_nothing_behind(tmp_path: Path) -> None:
    from app.core.task_context import OperationCancelled

    class _CancelAfterFirstPage:
        def __init__(self) -> None:
            self.checks = 0

        def check_cancelled(self) -> None:
            self.checks += 1
            if self.checks > 2:
                raise OperationCancelled()

        def report_step(self, *_args) -> None:
            pass

        def report(self, *_args) -> None:
            pass

    source = _make_multipage_tiff(tmp_path / "digitalizacao.tif")
    output_dir = tmp_path / "saida"

    with pytest.raises(OperationCancelled):
        ImageConverter().convert(
            str(source), str(output_dir / "digitalizacao.png"), _CancelAfterFirstPage()
        )

    assert list(output_dir.iterdir()) == []


@pytest.mark.parametrize("target", ["gif", "webp"])
def test_animation_is_kept_when_the_target_can_hold_it(tmp_path: Path, target: str) -> None:
    source = _make_animated_gif(tmp_path / "animacao.gif")
    destination = tmp_path / "saida" / f"animacao.{target}"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    with Image.open(destination) as image:
        assert image.n_frames == 3


def test_animated_gif_to_png_keeps_the_first_frame(tmp_path: Path) -> None:
    source = _make_animated_gif(tmp_path / "animacao.gif")
    destination = tmp_path / "animacao.png"

    result = ImageConverter().convert(str(source), str(destination))

    assert result.success, result.error_message
    assert result.output_path == str(destination)
    with Image.open(destination) as image:
        assert getattr(image, "n_frames", 1) == 1
        assert image.convert("RGB").getpixel((0, 0)) == (0, 30, 200)
