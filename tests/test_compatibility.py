"""
Testes de app.core.converter / app.core.merger (item 34 do briefing).

Usa um conversor/merger falso (double de teste) para verificar a
lógica do registro de compatibilidade sem depender de Pillow, pypdf
ou qualquer biblioteca externa — o próprio briefing pede que nenhuma
conversão real exista ainda nas Fases 1-2.
"""

from __future__ import annotations

from app.core.converter import BaseConverter, CompatibilityRegistry, ConversionResult
from app.core.merger import BaseMerger, MergeCompatibilityRegistry, MergeResult
from app.core.task_context import TaskContext


class _FakeImageConverter(BaseConverter):
    @property
    def source_formats(self) -> set[str]:
        return {"png", "jpg"}

    @property
    def target_formats(self) -> set[str]:
        return {"webp"}

    def convert(
        self, input_path: str, output_path: str, context: TaskContext | None = None
    ) -> ConversionResult:
        return ConversionResult(success=True, input_path=input_path, output_path=output_path)


class _FakePdfMerger(BaseMerger):
    @property
    def accepted_formats(self) -> set[str]:
        return {"pdf"}

    @property
    def output_format(self) -> str:
        return "pdf"

    def merge(
        self,
        input_paths: list[str],
        output_path: str,
        context: TaskContext | None = None,
    ) -> MergeResult:
        return MergeResult(success=True, input_paths=input_paths, output_path=output_path)


def test_empty_registry_never_allows_conversion() -> None:
    registry = CompatibilityRegistry()
    assert not registry.can_convert("png", "jpg")


def test_registered_converter_is_found() -> None:
    registry = CompatibilityRegistry()
    registry.register(_FakeImageConverter())

    assert registry.can_convert("png", "webp")
    assert not registry.can_convert("png", "pdf")
    assert registry.get_converter("jpg", "webp") is not None


def test_available_targets_for_many_is_intersection() -> None:
    registry = CompatibilityRegistry()
    registry.register(_FakeImageConverter())

    # png e jpg convertem para webp -> interseção deve conter webp
    assert registry.available_targets_for_many({"png", "jpg"}) == {"webp"}
    # docx não tem conversor registrado -> interseção fica vazia
    assert registry.available_targets_for_many({"png", "docx"}) == set()


def test_empty_merge_registry_never_allows_merge() -> None:
    registry = MergeCompatibilityRegistry()
    assert not registry.can_merge(["pdf", "pdf"])


def test_registered_merger_is_found() -> None:
    registry = MergeCompatibilityRegistry()
    registry.register(_FakePdfMerger())

    assert registry.can_merge(["pdf", "pdf"])
    assert not registry.can_merge(["pdf", "docx"])
    assert registry.get_merger(["pdf", "pdf"]) is not None
