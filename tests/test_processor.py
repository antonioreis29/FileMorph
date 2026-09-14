"""
Testes do orquestrador `FileProcessor`.

O foco é o que protege os arquivos do usuário: onde cada resultado é
gravado, a garantia de que dois arquivos do mesmo lote — inclusive rodando
em paralelo — nunca disputam o mesmo destino, e a recusa de qualquer
junção que substituiria uma das entradas.

Nada aqui precisa de Qt: o processador recebe a fila por injeção, e os
testes usam a `SynchronousTaskQueue` (ou uma fila com threads de verdade,
no teste de paralelismo).
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from app.core.converter import BaseConverter, CompatibilityRegistry, ConversionResult
from app.core.merger import BaseMerger, MergeCompatibilityRegistry, MergeResult
from app.core.processor import BatchRequest, FileProcessor
from app.core.task_context import TaskContext
from app.core.task_runner import SynchronousTaskQueue

ROOT = Path(__file__).resolve().parent.parent


class _RecordingConverter(BaseConverter):
    """Conversor de mentira: grava no destino pedido o nome da origem, para
    os testes verem quem escreveu cada arquivo. Aceita qualquer extensão de
    imagem das usadas aqui, e recusa `.txt` para simular um arquivo ruim."""

    def __init__(self, barrier: threading.Barrier | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._barrier = barrier
        self._lock = threading.Lock()

    @property
    def source_formats(self) -> set[str]:
        return {"png", "jpg", "txt"}

    @property
    def target_formats(self) -> set[str]:
        return {"png", "jpg", "webp"}

    def convert(
        self, input_path: str, output_path: str, context: TaskContext | None = None
    ) -> ConversionResult:
        with self._lock:
            self.calls.append((input_path, output_path))
        if self._barrier is not None:
            # As duas conversões chegam juntas ao momento de gravar.
            self._barrier.wait(timeout=5)
        if Path(input_path).suffix == ".txt":
            return ConversionResult(False, input_path, error_message="arquivo ruim de propósito")
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"convertido de {input_path}", encoding="utf-8")
        return ConversionResult(True, input_path, output_path=output_path)


def _processor(converter: BaseConverter, queue: SynchronousTaskQueue | None = None) -> FileProcessor:
    registry = CompatibilityRegistry()
    registry.register(converter)
    return FileProcessor(queue or SynchronousTaskQueue(), converters=registry)


def _results(queue: SynchronousTaskQueue) -> dict[str, object]:
    return {event[1]: event[2] for event in queue.events if event[0] == "finished"}


def _touch(path: Path, content: bytes = b"origem") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# --- Destino de cada arquivo ----------------------------------------------------


def test_output_keeps_original_name_with_new_extension(tmp_path: Path) -> None:
    source = _touch(tmp_path / "foto_viagem.png")
    output_dir = tmp_path / "saida"
    queue = SynchronousTaskQueue()

    tasks = _processor(_RecordingConverter(), queue).convert_batch(
        BatchRequest([str(source)], "jpg", str(output_dir), "replace")
    )

    result = _results(queue)[tasks[0].task_id]
    assert result.success
    assert Path(result.output_path).name == "foto_viagem.jpg"
    assert output_dir.is_dir()


def test_never_writes_over_the_source_file(tmp_path: Path) -> None:
    source = _touch(tmp_path / "imagem.png")

    tasks = _processor(_RecordingConverter()).convert_batch(
        BatchRequest([str(source)], "png", str(tmp_path), "replace")
    )

    assert source.read_bytes() == b"origem"
    assert Path(tasks[0].output_path).name == "imagem (1).png"


def test_copy_policy_preserves_existing_file(tmp_path: Path) -> None:
    source = _touch(tmp_path / "foto.png")
    existing = _touch(tmp_path / "saida" / "foto.jpg", b"arquivo antigo")

    tasks = _processor(_RecordingConverter()).convert_batch(
        BatchRequest([str(source)], "jpg", str(tmp_path / "saida"), "copy")
    )

    assert existing.read_bytes() == b"arquivo antigo"
    assert Path(tasks[0].output_path).name == "foto (1).jpg"


def test_ask_policy_defaults_to_preserving_existing_file(tmp_path: Path) -> None:
    source = _touch(tmp_path / "foto.png")
    existing = _touch(tmp_path / "foto.jpg", b"arquivo antigo")

    tasks = _processor(_RecordingConverter()).convert_batch(
        BatchRequest([str(source)], "jpg", str(tmp_path), "ask")
    )

    assert existing.read_bytes() == b"arquivo antigo"
    assert Path(tasks[0].output_path).name == "foto (1).jpg"


def test_replace_policy_overwrites_when_asked(tmp_path: Path) -> None:
    source = _touch(tmp_path / "foto.png")
    existing = _touch(tmp_path / "saida" / "foto.jpg", b"arquivo antigo")

    tasks = _processor(_RecordingConverter()).convert_batch(
        BatchRequest([str(source)], "jpg", str(tmp_path / "saida"), "replace")
    )

    assert tasks[0].output_path == str(existing)
    assert existing.read_text(encoding="utf-8") == f"convertido de {source}"


def test_unavailable_conversion_returns_friendly_failure(tmp_path: Path) -> None:
    source = _touch(tmp_path / "video.mp4")
    converter = _RecordingConverter()
    queue = SynchronousTaskQueue()

    tasks = _processor(converter, queue).convert_batch(
        BatchRequest([str(source)], "mp3", str(tmp_path), "replace")
    )

    result = _results(queue)[tasks[0].task_id]
    assert not result.success
    assert "não há conversor disponível" in (result.error_message or "").lower()
    assert converter.calls == []


# --- Mesmo nome no mesmo lote -----------------------------------------------------


def test_same_stem_from_two_folders_never_shares_a_destination(tmp_path: Path) -> None:
    """O caso que motivou o planejamento: `C:\\A\\foto.jpg` e `C:\\B\\foto.png`
    convertidos juntos para WEBP."""
    a = _touch(tmp_path / "A" / "foto.jpg")
    b = _touch(tmp_path / "B" / "foto.png")
    output_dir = tmp_path / "saida"

    tasks = _processor(_RecordingConverter()).convert_batch(
        BatchRequest([str(a), str(b)], "webp", str(output_dir), "replace")
    )

    assert [Path(t.output_path).name for t in tasks] == ["foto.webp", "foto (1).webp"]
    assert (output_dir / "foto.webp").read_text(encoding="utf-8") == f"convertido de {a}"
    assert (output_dir / "foto (1).webp").read_text(encoding="utf-8") == f"convertido de {b}"


def test_three_collisions_produce_three_files(tmp_path: Path) -> None:
    sources = [_touch(tmp_path / f"p{i}" / "foto.png") for i in range(3)]
    output_dir = tmp_path / "saida"

    _processor(_RecordingConverter()).convert_batch(
        BatchRequest([str(s) for s in sources], "jpg", str(output_dir), "copy")
    )

    assert sorted(p.name for p in output_dir.iterdir()) == [
        "foto (1).jpg",
        "foto (2).jpg",
        "foto.jpg",
    ]


class _ThreadedQueue:
    """Uma fila que roda todas as tarefas ao mesmo tempo, em threads de
    verdade — o cenário da `TaskQueue` com vários processos simultâneos."""

    def __init__(self) -> None:
        self.results: dict[str, object] = {}
        self._threads: list[threading.Thread] = []

    def enqueue(self, task_id, func, *args, **kwargs) -> None:
        def run() -> None:
            self.results[task_id] = func(TaskContext(), *args, **kwargs)

        thread = threading.Thread(target=run)
        self._threads.append(thread)
        thread.start()

    def cancel(self, task_id: str) -> None:  # pragma: no cover — não usado
        pass

    def cancel_all(self) -> None:  # pragma: no cover — não usado
        pass

    def join(self) -> None:
        for thread in self._threads:
            thread.join(timeout=10)


def test_parallel_conversions_with_the_same_stem_keep_both_results(tmp_path: Path) -> None:
    """As duas tarefas gravam no mesmo instante (a barreira as segura até
    as duas chegarem lá). Com o destino decidido dentro de cada thread,
    as duas escolheriam `foto.webp`; planejado antes, cada uma tem o seu."""
    sources = [_touch(tmp_path / f"pasta{i}" / "foto.png") for i in range(4)]
    output_dir = tmp_path / "saida"
    converter = _RecordingConverter(barrier=threading.Barrier(len(sources)))
    registry = CompatibilityRegistry()
    registry.register(converter)
    queue = _ThreadedQueue()

    tasks = FileProcessor(queue, converters=registry).convert_batch(
        BatchRequest([str(s) for s in sources], "webp", str(output_dir), "replace")
    )
    queue.join()

    written = {p.name: p.read_text(encoding="utf-8") for p in output_dir.iterdir()}
    assert len(written) == len(sources)
    assert sorted(written.values()) == sorted(f"convertido de {s}" for s in sources)
    assert all(result.success for result in queue.results.values())
    assert len({t.output_path for t in tasks}) == len(sources)


def test_real_conversion_with_unicode_names_and_folders_with_spaces(tmp_path: Path) -> None:
    """Com o conversor de imagens de verdade: nomes com acento e pastas com
    espaço, de duas pastas diferentes, no mesmo lote."""
    pytest.importorskip("PIL")
    from PIL import Image

    from app.converters.image_converter import ImageConverter

    first = tmp_path / "Fotos de Férias" / "praia ção.png"
    second = tmp_path / "Outra Pasta Com Espaço" / "praia ção.jpg"
    for path, mode in ((first, "RGBA"), (second, "RGB")):
        path.parent.mkdir(parents=True)
        Image.new(mode, (30, 20), (10, 100, 200)).save(path)
    before = {p: p.read_bytes() for p in (first, second)}
    output_dir = tmp_path / "Saída Convertida"
    queue = SynchronousTaskQueue()

    tasks = _processor(ImageConverter(), queue).convert_batch(
        BatchRequest([str(first), str(second)], "webp", str(output_dir), "copy")
    )

    results = _results(queue)
    assert all(results[t.task_id].success for t in tasks)
    assert sorted(p.name for p in output_dir.iterdir()) == ["praia ção (1).webp", "praia ção.webp"]
    assert {p: p.read_bytes() for p in (first, second)} == before


# --- Lote com sucesso e erro ------------------------------------------------------


def test_batch_mixing_success_and_error_reports_each_file(tmp_path: Path) -> None:
    good = _touch(tmp_path / "boa.png")
    bad = _touch(tmp_path / "ruim.txt")
    other = _touch(tmp_path / "outra.jpg")
    queue = SynchronousTaskQueue()

    tasks = _processor(_RecordingConverter(), queue).convert_batch(
        BatchRequest([str(good), str(bad), str(other)], "webp", str(tmp_path / "saida"), "copy")
    )

    results = _results(queue)
    by_input = {t.affected_paths[0]: results[t.task_id] for t in tasks}
    assert by_input[str(good)].success
    assert not by_input[str(bad)].success
    assert by_input[str(other)].success
    assert sorted(p.name for p in (tmp_path / "saida").iterdir()) == ["boa.webp", "outra.webp"]


def test_each_task_names_the_file_it_affects(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.png")
    b = _touch(tmp_path / "b.png")

    tasks = _processor(_RecordingConverter()).plan_conversion(
        BatchRequest([str(a), str(b)], "jpg", str(tmp_path / "saida"), "copy")
    )

    assert [t.affected_paths for t in tasks] == [(str(a),), (str(b),)]
    assert len({t.task_id for t in tasks}) == 2


# --- Junção: o destino nunca é uma entrada ---------------------------------------------


class _WritingMerger(BaseMerger):
    """Merger que grava de verdade no destino — se chegasse a ser chamado com
    um destino que é uma entrada, destruiria o original."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def accepted_formats(self) -> set[str]:
        return {"pdf"}

    @property
    def output_format(self) -> str:
        return "pdf"

    def merge(self, input_paths, output_path, context=None) -> MergeResult:
        self.calls.append(output_path)
        Path(output_path).write_bytes(b"juntado")
        return MergeResult(True, list(input_paths), output_path=output_path)


def _merge_processor(merger: BaseMerger) -> FileProcessor:
    registry = MergeCompatibilityRegistry()
    registry.register(merger)
    return FileProcessor(SynchronousTaskQueue(), mergers=registry)


@pytest.mark.parametrize("which", [0, 1, 2])
def test_merge_refuses_to_replace_any_input(tmp_path: Path, which: int) -> None:
    inputs = [_touch(tmp_path / f"{name}.pdf", f"original {name}".encode()) for name in "abc"]
    before = [p.read_bytes() for p in inputs]
    merger = _WritingMerger()

    result = _merge_processor(merger).plan_merge(
        [str(p) for p in inputs], str(inputs[which])
    ).run(TaskContext())

    assert not result.success
    assert inputs[which].name in (result.error_message or "")
    assert merger.calls == []
    assert [p.read_bytes() for p in inputs] == before


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="nomes sem distinção de maiúsculas são do Windows")
def test_merge_refuses_an_input_written_in_other_case(tmp_path: Path) -> None:
    a = _touch(tmp_path / "Contrato.pdf")
    b = _touch(tmp_path / "anexo.pdf")
    processor = _merge_processor(_WritingMerger())

    other_spelling = str(tmp_path / "CONTRATO.PDF").replace("\\", "/")
    assert processor.merge_destination_conflict([str(a), str(b)], other_spelling) == str(a)
    result = processor.plan_merge([str(a), str(b)], other_spelling).run(TaskContext())

    assert not result.success
    assert a.read_bytes() == b"origem"


def test_merge_task_lists_every_input_as_affected(tmp_path: Path) -> None:
    inputs = [str(_touch(tmp_path / f"{n}.pdf")) for n in "ab"]

    task = _merge_processor(_WritingMerger()).plan_merge(inputs, str(tmp_path / "final.pdf"))

    assert task.affected_paths == tuple(inputs)
    assert task.output_path == str(tmp_path / "final.pdf")


# --- O núcleo não depende de Qt ------------------------------------------------------------


def test_core_modules_import_without_qt() -> None:
    """As regras de negócio precisam ser testáveis sem carregar o PySide6."""
    code = (
        "import sys\n"
        "import app.core.processor, app.core.batch, app.core.output_planner\n"
        "import app.converters, app.mergers, app.organizers\n"
        "loaded = sorted(m for m in sys.modules if m.split('.')[0] == 'PySide6')\n"
        "print(loaded)\n"
        "sys.exit(1 if loaded else 0)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
