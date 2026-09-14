"""
Testes do que o `ffmpeg_manager` decide sem rodar o FFmpeg: a leitura da
saída dele e a procura pelo programa.

A procura tem uma ordem que importa para a versão distribuída: o FFmpeg
que vem junto com o FileMorph vence o que o usuário configurou, que vence o
que estiver no PATH — e nenhum deles existir não pode ser um erro. Os
testes montam cada cenário numa pasta temporária, com arquivos vazios no
lugar dos executáveis; a versão é lida por uma função de mentira, então
nada é executado.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.utils.ffmpeg_manager import (
    SOURCE_BUNDLED,
    SOURCE_CONFIGURED,
    SOURCE_PATH,
    FFmpegManager,
    _parse_encoders,
    detect_ffmpeg,
    friendly_error,
    parse_duration,
    parse_progress,
)

EXE = ".exe" if os.name == "nt" else ""


def _fake_program(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}{EXE}"
    path.write_bytes(b"")
    return path


def _version_of(command) -> str:
    return f"versao-de:{Path(command[0]).parent.name}"


def _nothing_in_path(_name: str) -> None:
    return None


# --- Leitura da saída do FFmpeg -----------------------------------------------


def test_parse_duration_reads_the_header_line() -> None:
    line = "  Duration: 00:03:21.53, start: 0.000000, bitrate: 130 kb/s"
    assert parse_duration(line) == pytest.approx(201.53)


def test_parse_duration_ignores_unknown_duration() -> None:
    assert parse_duration("  Duration: N/A, bitrate: N/A") is None
    assert parse_duration("frame=  120 fps=30") is None


def test_parse_progress_reads_microseconds() -> None:
    assert parse_progress("out_time_us=10240000") == pytest.approx(10.24)


def test_parse_progress_reads_timestamp() -> None:
    assert parse_progress("out_time=00:00:10.240000") == pytest.approx(10.24)


def test_parse_progress_ignores_out_time_ms() -> None:
    """`out_time_ms` é publicado em microssegundos por herança do FFmpeg.

    Aceitá-la faria o progresso correr mil vezes mais rápido do que a
    conversão — a barra chegaria a 100% no primeiro aviso.
    """
    assert parse_progress("out_time_ms=10240000") is None


def test_parse_progress_survives_the_initial_invalid_timestamp() -> None:
    assert parse_progress("out_time=-00:00:00.000001") == 0.0
    assert parse_progress("out_time_us=N/A") is None
    assert parse_progress("speed=1.02x") is None


def test_parse_encoders_reads_the_names() -> None:
    output = (
        "Encoders:\n"
        " V..... = Video\n"
        " ------\n"
        " A....D aac                  AAC (Advanced Audio Coding)\n"
        " V....D libx264              libx264 H.264 / AVC\n"
    )
    assert _parse_encoders(output) == {"aac", "libx264"}


def test_friendly_error_translates_a_known_failure() -> None:
    message = friendly_error(["x.mp3: Invalid data found when processing input"])
    assert "corrompido" in message


def test_friendly_error_falls_back_to_the_last_line() -> None:
    message = friendly_error(["Alguma coisa estranha aconteceu"])
    assert "Alguma coisa estranha aconteceu" in message


# --- Procura pelo FFmpeg ---------------------------------------------------------


def test_bundled_ffmpeg_comes_first(tmp_path: Path) -> None:
    bundled = _fake_program(tmp_path / "vendor" / "ffmpeg", "ffmpeg")
    probe = _fake_program(tmp_path / "vendor" / "ffmpeg", "ffprobe")
    configured = _fake_program(tmp_path / "configurado", "ffmpeg")
    in_path = _fake_program(tmp_path / "path", "ffmpeg")

    status = detect_ffmpeg(
        bundled_dir=tmp_path / "vendor" / "ffmpeg",
        configured_path=str(configured),
        which=lambda name: str(in_path) if name == "ffmpeg" else None,
        read_version=_version_of,
    )

    assert status.available
    assert status.source == SOURCE_BUNDLED
    assert status.executable_path == str(bundled)
    assert status.ffprobe_path == str(probe)
    assert status.version == "versao-de:ffmpeg"


def test_configured_ffmpeg_is_used_when_nothing_is_bundled(tmp_path: Path) -> None:
    configured = _fake_program(tmp_path / "Meu FFmpeg" / "bin", "ffmpeg")
    in_path = _fake_program(tmp_path / "path", "ffmpeg")

    by_folder = detect_ffmpeg(
        bundled_dir=tmp_path / "vendor-vazio",
        configured_path=str(configured.parent),
        which=lambda name: str(in_path),
        read_version=_version_of,
    )
    by_file = detect_ffmpeg(
        bundled_dir=tmp_path / "vendor-vazio",
        configured_path=str(configured),
        which=lambda name: str(in_path),
        read_version=_version_of,
    )

    for status in (by_folder, by_file):
        assert status.source == SOURCE_CONFIGURED
        assert status.executable_path == str(configured)
        assert status.ffprobe_path is None  # não há ffprobe ao lado dele


def test_path_ffmpeg_is_the_last_option(tmp_path: Path) -> None:
    in_path = _fake_program(tmp_path / "path", "ffmpeg")
    probe = _fake_program(tmp_path / "path", "ffprobe")
    programs = {"ffmpeg": str(in_path), "ffprobe": str(probe)}

    status = detect_ffmpeg(
        bundled_dir=tmp_path / "vendor-vazio",
        configured_path=str(tmp_path / "configurado-que-sumiu"),
        which=programs.get,
        read_version=_version_of,
    )

    assert status.source == SOURCE_PATH
    assert status.executable_path == str(in_path)
    assert status.ffprobe_path == str(probe)


def test_missing_ffmpeg_is_not_an_error(tmp_path: Path) -> None:
    status = detect_ffmpeg(
        bundled_dir=tmp_path / "vendor-vazio",
        configured_path=None,
        which=_nothing_in_path,
        read_version=_version_of,
    )

    assert not status.available
    assert status.executable_path is None
    assert status.source is None


def test_changing_the_configured_path_forgets_the_previous_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str | None] = []

    def detect(**options):
        seen.append(options.get("configured_path"))
        from app.utils.ffmpeg_manager import FFmpegStatus

        return FFmpegStatus(False, None, None)

    monkeypatch.setattr("app.utils.ffmpeg_manager.detect_ffmpeg", detect)
    manager = FFmpegManager()

    manager.status()
    manager.set_configured_path("C:/ffmpeg/bin")
    manager.status()
    manager.status()  # guardado: não detecta de novo

    assert seen == [None, "C:/ffmpeg/bin"]


def test_the_suite_never_detects_a_real_ffmpeg() -> None:
    """A trava de `conftest.py`: o FFmpeg global responde "ausente" em todo
    teste, esteja ele instalado nesta máquina ou não."""
    from app.utils.ffmpeg_manager import ffmpeg_manager

    assert not ffmpeg_manager.is_available()
    assert ffmpeg_manager.available_encoders() == frozenset()
