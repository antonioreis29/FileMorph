"""
Testes do orquestrador `FileProcessor` (item 34 do briefing).

O foco aqui é a decisão de *onde* gravar o resultado — a parte que
protege os arquivos do usuário (itens 18 e 21): nunca sobrescrever o
próprio arquivo de origem, respeitar a política de conflito e criar a
pasta de destino quando ela não existe.

Os testes chamam `_convert_one` diretamente, sem passar pela fila:
assim não é preciso um loop de eventos Qt para verificar a regra.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.converter import BaseConverter, CompatibilityRegistry, ConversionResult
from app.core.processor import FileProcessor
from app.core.task_context import NULL_CONTEXT, TaskContext


class _RecordingConverter(BaseConverter):
    """Conversor de mentira que apenas anota o caminho de saída pedido e
    cria o arquivo, para que os testes vejam a decisão do processador."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    @property
    def source_formats(self) -> set[str]:
        return {"png", "jpg"}

    @property
    def target_formats(self) -> set[str]:
        return {"png", "jpg"}

    def convert(
        self, input_path: str, output_path: str, context: TaskContext | None = None
    ) -> ConversionResult:
        self.calls.append((input_path, output_path))
        Path(output_path).write_bytes(b"convertido")
        return ConversionResult(success=True, input_path=input_path, output_path=output_path)


@pytest.fixture
def converter(monkeypatch: pytest.MonkeyPatch) -> _RecordingConverter:
    """Substitui o registro global por um isolado, para que o teste não
    dependa de quais conversores reais estão instalados."""
    registry = CompatibilityRegistry()
    fake = _RecordingConverter()
    registry.register(fake)
    monkeypatch.setattr("app.core.processor.compatibility_registry", registry)
    return fake


def _processor() -> FileProcessor:
    # A fila só é usada por `convert_batch`; `_convert_one` não a toca.
    return FileProcessor(task_queue=None)  # type: ignore[arg-type]


def test_output_keeps_original_name_with_new_extension(
    tmp_path: Path, converter: _RecordingConverter
) -> None:
    source = tmp_path / "foto_viagem.png"
    source.write_bytes(b"origem")
    output_dir = tmp_path / "saida"

    result = _processor()._convert_one(NULL_CONTEXT, str(source), "jpg", str(output_dir), "replace")

    assert result.success
    assert Path(result.output_path or "").name == "foto_viagem.jpg"
    assert output_dir.is_dir()  # a pasta de destino é criada se faltar


def test_never_writes_over_the_source_file(
    tmp_path: Path, converter: _RecordingConverter
) -> None:
    """Converter PNG para PNG na mesma pasta não pode gravar por cima do
    original — o resultado vira uma cópia numerada."""
    source = tmp_path / "imagem.png"
    source.write_bytes(b"origem")

    result = _processor()._convert_one(NULL_CONTEXT, str(source), "png", str(tmp_path), "replace")

    assert result.success
    assert result.output_path != str(source)
    assert source.read_bytes() == b"origem"
    assert Path(result.output_path or "").name == "imagem (1).png"


def test_copy_policy_preserves_existing_file(
    tmp_path: Path, converter: _RecordingConverter
) -> None:
    source = tmp_path / "foto.png"
    source.write_bytes(b"origem")
    output_dir = tmp_path / "saida"
    output_dir.mkdir()
    existing = output_dir / "foto.jpg"
    existing.write_bytes(b"arquivo antigo")

    result = _processor()._convert_one(NULL_CONTEXT, str(source), "jpg", str(output_dir), "copy")

    assert result.success
    assert existing.read_bytes() == b"arquivo antigo"
    assert Path(result.output_path or "").name == "foto (1).jpg"


def test_ask_policy_defaults_to_preserving_existing_file(
    tmp_path: Path, converter: _RecordingConverter
) -> None:
    """'ask' significa que a interface deveria ter resolvido o conflito
    antes; se chegou assim até aqui, o padrão seguro é não destruir
    nada."""
    source = tmp_path / "foto.png"
    source.write_bytes(b"origem")
    existing = tmp_path / "foto.jpg"
    existing.write_bytes(b"arquivo antigo")

    result = _processor()._convert_one(NULL_CONTEXT, str(source), "jpg", str(tmp_path), "ask")

    assert existing.read_bytes() == b"arquivo antigo"
    assert Path(result.output_path or "").name == "foto (1).jpg"


def test_replace_policy_overwrites_when_asked(
    tmp_path: Path, converter: _RecordingConverter
) -> None:
    source = tmp_path / "foto.png"
    source.write_bytes(b"origem")
    existing = tmp_path / "foto.jpg"
    existing.write_bytes(b"arquivo antigo")

    result = _processor()._convert_one(NULL_CONTEXT, str(source), "jpg", str(tmp_path), "replace")

    assert result.output_path == str(existing)
    assert existing.read_bytes() == b"convertido"


def test_unavailable_conversion_returns_friendly_failure(
    tmp_path: Path, converter: _RecordingConverter
) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"origem")

    result = _processor()._convert_one(NULL_CONTEXT, str(source), "mp3", str(tmp_path), "replace")

    assert not result.success
    assert "não há conversor disponível" in (result.error_message or "").lower()
    assert converter.calls == []
