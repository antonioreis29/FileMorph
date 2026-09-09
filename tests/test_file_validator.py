"""Testes de app.core.file_validator (item 34 do briefing)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.core.file_validator import get_file_category, is_known_extension, validate_paths


def test_is_known_extension_true_for_supported_formats() -> None:
    assert is_known_extension("foto.PNG")
    assert is_known_extension("video.mp4")
    assert is_known_extension("planilha.xlsx")


def test_is_known_extension_false_for_unsupported_formats() -> None:
    assert not is_known_extension("arquivo.exe")
    assert not is_known_extension("sem_extensao")


def test_get_file_category() -> None:
    assert get_file_category("foto.png") == "imagem"
    assert get_file_category("video.mp4") == "video"
    assert get_file_category("arquivo.exe") is None


def test_validate_paths_separates_valid_and_invalid() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        valid_file = Path(tmp) / "foto.png"
        valid_file.write_bytes(b"fake-image-content")

        invalid_ext_file = Path(tmp) / "arquivo.exe"
        invalid_ext_file.write_bytes(b"fake")

        nonexistent = str(Path(tmp) / "nao_existe.png")

        valid, invalid = validate_paths([str(valid_file), str(invalid_ext_file), nonexistent])

        assert str(valid_file) in valid
        assert str(invalid_ext_file) in invalid
        assert nonexistent in invalid
