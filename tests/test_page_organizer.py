"""
Testes da organização de páginas.

O que mais importa numa reorganização está nos requisitos da própria
funcionalidade, e cada um tem teste aqui: a ordem pedida é a ordem do
arquivo final; nenhuma página é duplicada nem removida; a qualidade das
páginas é a original; o arquivo de origem nunca muda; e o que não dá para
processar vira uma mensagem que o usuário entende.

Como nos outros testes de PDF, os documentos são gerados na hora e o
resultado é relido com PyMuPDF. Cada página escreve o próprio número, e é
lendo esse texto que os testes conferem a ordem.
"""

from __future__ import annotations

import hashlib
import io
import random
from pathlib import Path

import pytest

pytest.importorskip("pymupdf", reason="PyMuPDF é a dependência da organização de páginas")
pytest.importorskip("PIL", reason="Pillow gera as imagens embutidas nas páginas")

import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

from app.core.page_organizer import (  # noqa: E402
    BasePageOrganizer,
    PageOrderResult,
    PageOrganizerError,
    PageOrganizerRegistry,
    PagePreview,
    check_page_order,
    describe_page_order,
    is_original_order,
    move_pages,
)
from app.core.processor import FileProcessor  # noqa: E402
from app.core.task_context import NULL_CONTEXT, OperationCancelled, TaskContext  # noqa: E402
from app.organizers import register_builtin_organizers  # noqa: E402
from app.organizers import pdf_organizer  # noqa: E402
from app.organizers.pdf_organizer import PdfPageOrganizer  # noqa: E402
from app.utils.file_utils import TEMP_WRITE_SUFFIX  # noqa: E402


def _make_pdf(path: Path, pages: int) -> Path:
    """PDF cujas páginas dizem o próprio número e têm larguras diferentes."""
    document = pymupdf.open()
    for number in range(1, pages + 1):
        page = document.new_page(width=300 + number, height=400)
        page.insert_text((40, 80), f"Pagina {number}", fontsize=20)
    document.save(path)
    document.close()
    return path


def _labels(path: Path) -> list[str]:
    with pymupdf.open(path) as document:
        return [page.get_text().strip() for page in document]


def _leftovers(folder: Path) -> list[Path]:
    return [p for p in folder.iterdir() if TEMP_WRITE_SUFFIX in p.name]


# --- Regras da ordem ---------------------------------------------------------


def test_a_valid_order_uses_every_page_exactly_once() -> None:
    check_page_order([2, 0, 3, 1], 4)  # não levanta


@pytest.mark.parametrize(
    "order",
    [
        [0, 0, 1, 2],  # página duplicada
        [0, 1, 2],  # página faltando
        [0, 1, 2, 9],  # página que não existe
        [0, 1, 2, 3, 3],  # tamanho maior que o documento
    ],
)
def test_an_order_that_duplicates_or_drops_pages_is_refused(order: list[int]) -> None:
    with pytest.raises(PageOrganizerError):
        check_page_order(order, 4)


def test_original_order_is_recognized() -> None:
    assert is_original_order([0, 1, 2])
    assert is_original_order([])
    assert not is_original_order([1, 0, 2])


def test_moving_a_page_to_the_front() -> None:
    """O exemplo do pedido, um passo por vez: 1 2 3 4 -> 3 1 2 4."""
    assert move_pages([0, 1, 2, 3], [2], 0) == ([2, 0, 1, 3], 0)


def test_moving_a_page_forward_counts_the_destination_in_the_current_order() -> None:
    # Soltar a página 1 antes da página 4 (posição 3) a deixa na posição 2.
    assert move_pages([0, 1, 2, 3], [0], 3) == ([1, 2, 0, 3], 2)


def test_moving_to_the_end() -> None:
    assert move_pages([0, 1, 2, 3], [1], 4) == ([0, 2, 3, 1], 3)


def test_moving_several_pages_keeps_them_together_and_in_order() -> None:
    assert move_pages([0, 1, 2, 3, 4, 5], [4, 1], 0) == ([1, 4, 0, 2, 3, 5], 0)


def test_dropping_pages_onto_themselves_changes_nothing() -> None:
    assert move_pages([0, 1, 2, 3], [1, 2], 2) == ([0, 1, 2, 3], 1)


def test_positions_and_destination_outside_the_document_are_contained() -> None:
    assert move_pages([0, 1, 2], [7, -1], 1) == ([0, 1, 2], 1)
    assert move_pages([0, 1, 2], [0], 99) == ([1, 2, 0], 2)


def test_any_move_produces_a_permutation() -> None:
    """A garantia de que arrastar nunca duplica nem perde página, conferida
    num volume de combinações que nenhum teste de exemplo cobriria."""
    rng = random.Random(20260914)
    for _ in range(2000):
        size = rng.randint(1, 30)
        order = rng.sample(range(size), size)
        positions = rng.sample(range(size), rng.randint(0, size))
        destination = rng.randint(-2, size + 2)

        new_order, start = move_pages(order, positions, destination)

        assert sorted(new_order) == list(range(size))
        if positions:
            moved = [order[p] for p in sorted(positions)]
            assert new_order[start : start + len(moved)] == moved


def test_order_description_uses_the_numbers_the_user_sees() -> None:
    assert describe_page_order([2, 0, 3, 1]) == "3, 1, 4, 2"


def test_order_description_summarizes_long_runs() -> None:
    order = [49] + list(range(49)) + list(range(50, 100))
    assert describe_page_order(order) == "50, 1–49, 51–100"
    assert describe_page_order(list(reversed(range(10)))) == "10–1"
    # Duas páginas seguidas não viram intervalo: "1–2" diria menos que "1, 2".
    assert describe_page_order([4, 0, 1, 2, 3]) == "5, 1–4"
    assert describe_page_order([2, 0, 1]) == "3, 1, 2"


def test_order_description_can_be_cut_short() -> None:
    order = [5, 3, 9, 1, 7, 0, 8, 2, 6, 4]
    assert describe_page_order(order, max_parts=3) == "6, 4, 10, …"


# --- Reorganizar um PDF ---------------------------------------------------------


def test_reorders_pages_in_the_requested_order(tmp_path: Path) -> None:
    """O exemplo do pedido: 1, 2, 3, 4 -> 3, 1, 4, 2."""
    source = _make_pdf(tmp_path / "relatorio.pdf", pages=4)
    destination = tmp_path / "relatorio_reorganizado.pdf"

    result = PdfPageOrganizer().reorder(str(source), str(destination), [2, 0, 3, 1])

    assert result.success, result.error_message
    assert result.output_path == str(destination)
    assert _labels(destination) == ["Pagina 3", "Pagina 1", "Pagina 4", "Pagina 2"]


def test_every_page_survives_exactly_once(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "livro.pdf", pages=30)
    order = random.Random(7).sample(range(30), 30)
    destination = tmp_path / "livro_novo.pdf"

    result = PdfPageOrganizer().reorder(str(source), str(destination), order)

    assert result.success, result.error_message
    assert _labels(destination) == [f"Pagina {page + 1}" for page in order]
    with pymupdf.open(destination) as document:
        # A página inteira foi junto, não só o texto: o tamanho dela também.
        assert [round(page.rect.width) for page in document] == [301 + p for p in order]


def test_many_pages_are_reordered(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "grande.pdf", pages=400)
    order = list(reversed(range(400)))
    destination = tmp_path / "grande_invertido.pdf"

    result = PdfPageOrganizer().reorder(str(source), str(destination), order)

    assert result.success, result.error_message
    labels = _labels(destination)
    assert labels[0] == "Pagina 400"
    assert labels[-1] == "Pagina 1"
    assert len(labels) == 400


def test_page_content_keeps_its_original_quality(tmp_path: Path) -> None:
    """Nada é rasterizado nem recomprimido com perda: a foto em JPEG sai
    byte a byte igual, e toda imagem decodifica nos mesmos pixels."""
    document = pymupdf.open()
    jpeg = io.BytesIO()
    Image.new("RGB", (320, 200), (200, 40, 90)).save(jpeg, "JPEG", quality=71)
    png = io.BytesIO()
    Image.new("RGB", (320, 200), (30, 140, 90)).save(png, "PNG")
    for stream in (jpeg, png):
        page = document.new_page()
        page.insert_image(pymupdf.Rect(20, 20, 340, 220), stream=stream.getvalue())
    source = tmp_path / "fotos.pdf"
    document.save(source)
    document.close()

    def image_fingerprints(path: Path) -> list[tuple[str, str]]:
        with pymupdf.open(path) as pdf:
            prints = []
            for page in pdf:
                xref = page.get_images()[0][0]
                raw = pdf.xref_stream_raw(xref) if pdf.xref_get_key(xref, "Filter")[1] == "/DCTDecode" else b""
                prints.append(
                    (hashlib.sha1(raw).hexdigest(), hashlib.sha1(pdf.xref_stream(xref)).hexdigest())
                )
            return prints

    before = image_fingerprints(source)
    # Sem isto o teste passaria à toa se a foto não estivesse guardada como
    # JPEG: compararia dois resumos de nada.
    assert before[0][0] != hashlib.sha1(b"").hexdigest()
    destination = tmp_path / "fotos_invertidas.pdf"

    result = PdfPageOrganizer().reorder(str(source), str(destination), [1, 0])

    assert result.success, result.error_message
    assert image_fingerprints(destination) == list(reversed(before))


def test_bookmarks_and_internal_links_follow_their_pages(tmp_path: Path) -> None:
    document = pymupdf.open()
    for number in range(1, 5):
        document.new_page().insert_text((40, 80), f"Pagina {number}", fontsize=20)
    # Um link na página 1 que leva à página 4, e um marcador por capítulo.
    document[0].insert_link(
        {"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(40, 60, 200, 90), "page": 3}
    )
    document.set_toc([[1, "Capítulo A", 1], [1, "Capítulo C", 3], [2, "Seção D", 4]])
    source = tmp_path / "manual.pdf"
    document.save(source)
    document.close()
    destination = tmp_path / "manual_novo.pdf"

    result = PdfPageOrganizer().reorder(str(source), str(destination), [2, 0, 3, 1])

    assert result.success, result.error_message
    with pymupdf.open(destination) as reordered:
        # Página 1 foi para a posição 2; a 3, para a 1; a 4, para a 3.
        assert reordered.get_toc() == [[1, "Capítulo A", 2], [1, "Capítulo C", 1], [2, "Seção D", 3]]
        links = reordered[1].get_links()
        assert [link.get("page") for link in links] == [2]  # a página 4, agora na posição 3


def test_document_information_is_kept(tmp_path: Path) -> None:
    document = pymupdf.open()
    document.new_page()
    document.new_page()
    document.set_metadata({"title": "Relatório anual", "author": "Ana"})
    source = tmp_path / "anual.pdf"
    document.save(source)
    document.close()
    destination = tmp_path / "anual_novo.pdf"

    assert PdfPageOrganizer().reorder(str(source), str(destination), [1, 0]).success

    with pymupdf.open(destination) as reordered:
        assert reordered.metadata["title"] == "Relatório anual"
        assert reordered.metadata["author"] == "Ana"


def test_output_is_not_bloated(tmp_path: Path) -> None:
    """Um PDF que guarda os objetos comprimidos não pode sair com o dobro do
    tamanho só porque as páginas trocaram de lugar."""
    document = pymupdf.open()
    for number in range(60):
        document.new_page().insert_text((40, 80), f"Pagina {number} " * 12, fontsize=9)
    source = tmp_path / "compacto.pdf"
    document.save(source, garbage=3, deflate=True, use_objstms=1)
    document.close()
    destination = tmp_path / "compacto_novo.pdf"

    result = PdfPageOrganizer().reorder(str(source), str(destination), list(reversed(range(60))))

    assert result.success, result.error_message
    assert destination.stat().st_size <= source.stat().st_size * 1.1


def test_source_is_never_modified(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "original.pdf", pages=3)
    original_bytes = source.read_bytes()

    PdfPageOrganizer().reorder(str(source), str(tmp_path / "novo.pdf"), [2, 1, 0])

    assert source.read_bytes() == original_bytes


@pytest.mark.parametrize("order", [[0, 0, 1], [0, 1], [0, 1, 5]])
def test_invalid_order_fails_before_writing_anything(tmp_path: Path, order: list[int]) -> None:
    source = _make_pdf(tmp_path / "doc.pdf", pages=3)
    destination = tmp_path / "doc_novo.pdf"

    result = PdfPageOrganizer().reorder(str(source), str(destination), order)

    assert not result.success
    assert "duplicada ou removida" in (result.error_message or "")
    assert not destination.exists()
    assert _leftovers(tmp_path) == []


def test_refuses_to_write_over_the_original(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "contrato.pdf", pages=2)
    original_bytes = source.read_bytes()
    # O mesmo arquivo, escrito de outro jeito — no Windows, com outra caixa.
    same_file = tmp_path / "CONTRATO.PDF" if Path(str(source).upper()).exists() else source

    result = PdfPageOrganizer().reorder(str(source), str(same_file), [1, 0])

    assert not result.success
    assert "nunca altera o arquivo original" in (result.error_message or "")
    assert source.read_bytes() == original_bytes


def test_destination_must_be_a_pdf(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "doc.pdf", pages=2)

    result = PdfPageOrganizer().reorder(str(source), str(tmp_path / "doc.png"), [1, 0])

    assert not result.success
    assert not (tmp_path / "doc.png").exists()


def test_password_protected_pdf_gives_a_clear_message(tmp_path: Path) -> None:
    source = tmp_path / "protegido.pdf"
    document = pymupdf.open()
    document.new_page()
    document.new_page()
    document.save(
        source, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="dono", user_pw="segredo"
    )
    document.close()

    result = PdfPageOrganizer().reorder(str(source), str(tmp_path / "novo.pdf"), [1, 0])

    assert not result.success
    assert "senha" in (result.error_message or "")


def test_pdf_with_edit_restrictions_is_refused(tmp_path: Path) -> None:
    """Abre sem senha, mas o autor restringiu alterações. Gravá-lo
    reorganizado jogaria a proteção fora sem ninguém perceber."""
    source = tmp_path / "restrito.pdf"
    document = pymupdf.open()
    document.new_page()
    document.new_page()
    document.save(
        source,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="dono",
        user_pw="",
        permissions=pymupdf.PDF_PERM_PRINT,
    )
    document.close()
    destination = tmp_path / "novo.pdf"

    result = PdfPageOrganizer().reorder(str(source), str(destination), [1, 0])

    assert not result.success
    assert "proteção" in (result.error_message or "")
    assert not destination.exists()


def test_corrupted_pdf_gives_a_clear_message(tmp_path: Path) -> None:
    broken = tmp_path / "quebrado.pdf"
    broken.write_bytes(b"%PDF-1.4 mentira")

    result = PdfPageOrganizer().reorder(str(broken), str(tmp_path / "novo.pdf"), [0])

    assert not result.success
    assert "corrompido" in (result.error_message or "")


def test_missing_file_gives_a_clear_message(tmp_path: Path) -> None:
    result = PdfPageOrganizer().reorder(
        str(tmp_path / "sumiu.pdf"), str(tmp_path / "novo.pdf"), [0]
    )

    assert not result.success
    assert "não foi encontrado" in (result.error_message or "")


def test_existing_destination_survives_a_failed_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_pdf(tmp_path / "doc.pdf", pages=3)
    destination = _make_pdf(tmp_path / "ja_existia.pdf", pages=1)
    good_bytes = destination.read_bytes()

    def disco_cheio(_document, _path) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pdf_organizer, "_save", disco_cheio)

    result = PdfPageOrganizer().reorder(str(source), str(destination), [2, 1, 0])

    assert not result.success
    assert "No space left" in (result.error_message or "")
    assert destination.read_bytes() == good_bytes
    assert _leftovers(tmp_path) == []


def test_cancelling_after_the_save_discards_the_new_file(tmp_path: Path) -> None:
    """O último ponto seguro é depois de gravar e antes de ocupar o nome
    definitivo: desistir ali não pode deixar nada para trás."""
    source = _make_pdf(tmp_path / "doc.pdf", pages=3)
    destination = tmp_path / "doc_novo.pdf"
    checks: list[bool] = []

    def cancels_on_third_check() -> bool:
        checks.append(True)
        return len(checks) >= 3

    context = TaskContext(is_cancelled=cancels_on_third_check)

    with pytest.raises(OperationCancelled):
        PdfPageOrganizer().reorder(str(source), str(destination), [2, 1, 0], context)

    assert len(checks) == 3  # chegou mesmo ao ponto depois da gravação
    assert not destination.exists()
    assert _leftovers(tmp_path) == []


def test_cancelling_before_starting_writes_nothing(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "doc.pdf", pages=3)
    destination = tmp_path / "doc_novo.pdf"

    with pytest.raises(OperationCancelled):
        PdfPageOrganizer().reorder(
            str(source), str(destination), [2, 1, 0], TaskContext(is_cancelled=lambda: True)
        )

    assert not destination.exists()


def test_progress_is_reported_until_done(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "doc.pdf", pages=3)
    reported: list[int] = []

    result = PdfPageOrganizer().reorder(
        str(source), str(tmp_path / "novo.pdf"), [2, 1, 0], TaskContext(on_progress=reported.append)
    )

    assert result.success, result.error_message
    assert reported == sorted(reported)
    assert reported[-1] == 100


# --- Miniaturas ---------------------------------------------------------------------


def test_preview_counts_pages_and_draws_thumbnails_within_the_size(tmp_path: Path) -> None:
    document = pymupdf.open()
    document.new_page(width=595, height=842)  # retrato
    document.new_page(width=842, height=595)  # paisagem
    source = tmp_path / "misto.pdf"
    document.save(source)
    document.close()

    with PdfPageOrganizer().open_preview(str(source)) as preview:
        assert preview.page_count == 2
        portrait = preview.render_thumbnail(0, 144)
        landscape = preview.render_thumbnail(1, 144)

    assert abs(portrait.height - 144) <= 1 and portrait.width < portrait.height
    assert abs(landscape.width - 144) <= 1 and landscape.height < landscape.width
    for thumbnail in (portrait, landscape):
        assert len(thumbnail.samples) == thumbnail.width * thumbnail.height * 3


def test_preview_of_a_protected_pdf_explains_itself(tmp_path: Path) -> None:
    source = tmp_path / "protegido.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(
        source, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="dono", user_pw="segredo"
    )
    document.close()

    with pytest.raises(PageOrganizerError, match="senha"):
        PdfPageOrganizer().open_preview(str(source))


def test_preview_of_a_corrupted_pdf_explains_itself(tmp_path: Path) -> None:
    broken = tmp_path / "quebrado.pdf"
    broken.write_bytes(b"nao sou um pdf")

    with pytest.raises(PageOrganizerError, match="corrompido"):
        PdfPageOrganizer().open_preview(str(broken))


# --- Registro e processador ------------------------------------------------------------


def test_registered_organizer_answers_for_pdf_only() -> None:
    registry = PageOrganizerRegistry()

    registered = register_builtin_organizers(registry)

    assert registered
    assert registry.can_organize("pdf")
    assert registry.can_organize(".PDF")
    assert not registry.can_organize("png")
    assert registry.accepted_formats() == {"pdf"}
    assert register_builtin_organizers(registry) == []  # idempotente


class _RecordingOrganizer(BasePageOrganizer):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[int]]] = []

    @property
    def accepted_formats(self) -> set[str]:
        return {"pdf"}

    def open_preview(self, path: str) -> PagePreview:  # pragma: no cover — não usado
        raise PageOrganizerError("não usado")

    def reorder(self, input_path, output_path, page_order, context=None) -> PageOrderResult:
        self.calls.append((input_path, output_path, list(page_order)))
        return PageOrderResult(success=True, input_path=input_path, output_path=output_path)


@pytest.fixture
def organizer() -> _RecordingOrganizer:
    """Organizador de mentira, num registro isolado (ver `_processor`), para
    o teste não depender do que está instalado."""
    return _RecordingOrganizer()


def _processor(organizer: _RecordingOrganizer) -> FileProcessor:
    registry = PageOrganizerRegistry()
    registry.register(organizer)
    return FileProcessor(organizers=registry)


def test_processor_offers_organizing_for_exactly_one_supported_file(
    organizer: _RecordingOrganizer,
) -> None:
    processor = _processor(organizer)

    assert processor.can_organize_pages(["relatorio.pdf"])
    assert not processor.can_organize_pages(["a.pdf", "b.pdf"])
    assert not processor.can_organize_pages(["foto.png"])
    assert not processor.can_organize_pages([])
    assert processor.organizable_formats() == {"pdf"}


def test_processor_delegates_to_the_registered_organizer(organizer: _RecordingOrganizer) -> None:
    task = _processor(organizer).plan_organize("in.pdf", "out.pdf", [1, 0])

    result = task.run(NULL_CONTEXT)

    assert result.success
    assert organizer.calls == [("in.pdf", "out.pdf", [1, 0])]
    # A tarefa diz explicitamente qual arquivo da lista ela afeta.
    assert task.affected_paths == ("in.pdf",)
    assert task.output_path == "out.pdf"


def test_processor_explains_when_there_is_no_organizer(organizer: _RecordingOrganizer) -> None:
    processor = _processor(organizer)

    result = processor.plan_organize("planilha.xlsx", "saida.xlsx", [0]).run(NULL_CONTEXT)

    assert not result.success
    assert ".xlsx" in (result.error_message or "")
    with pytest.raises(PageOrganizerError):
        processor.open_page_preview("planilha.xlsx")
    assert organizer.calls == []


def test_processor_never_organizes_into_the_original_file(
    organizer: _RecordingOrganizer, tmp_path: Path
) -> None:
    """A proteção vale no processador, antes de chegar ao organizador — e com
    o nome escrito de outro jeito (maiúsculas), como o Windows aceita."""
    source = tmp_path / "relatorio.pdf"
    source.write_bytes(b"%PDF-1.4")

    result = _processor(organizer).plan_organize(
        str(source), str(tmp_path / "RELATORIO.PDF"), [0]
    ).run(NULL_CONTEXT)

    assert not result.success
    assert "original" in (result.error_message or "")
    assert organizer.calls == []
    assert source.read_bytes() == b"%PDF-1.4"
