"""
Testes dos conversores de áudio e vídeo.

Os testes de imagem e PDF rodam a conversão de verdade porque Pillow e
PyMuPDF são bibliotecas Python, instaladas junto com o projeto. O
FFmpeg não é: exigir que ele esteja no PATH da máquina transformaria a
suíte inteira em "pulado" para quem só quer rodar os testes — e faria o
resultado depender da compilação do FFmpeg que cada máquina tem.

A saída aqui é `tests/fake_ffmpeg.py`, um programa que imita o pedaço
do FFmpeg que o FileMorph realmente usa. Com ele, o código exercitado é
o de produção — a leitura do andamento, o encerramento do processo, a
tradução do erro, a gravação atômica —, e a única peça falsa é o
binário do outro lado do cano. Por rodarem um processo externo, estes
testes são de integração; a leitura da saída do FFmpeg e a detecção do
programa, que não rodam nada, estão em `test_ffmpeg_manager.py`.

O que estes testes protegem, em uma frase: uma conversão de mídia
interrompida ou com erro não pode deixar nada na pasta do usuário, e a
interface não pode oferecer um formato que esta instalação do FFmpeg
não sabe gerar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.converters import register_builtin_converters
from app.converters.audio_converter import AudioConverter
from app.converters.video_converter import VideoConverter, VideoToAudioConverter
from app.core.converter import CompatibilityRegistry
from app.core.task_context import OperationCancelled, TaskContext
from app.utils.ffmpeg_manager import FFmpegManager
from app.utils.file_utils import TEMP_WRITE_SUFFIX

pytestmark = pytest.mark.integration

FAKE_FFMPEG = Path(__file__).parent / "fake_ffmpeg.py"


def _manager(**options: object) -> FFmpegManager:
    """Um FFmpegManager apontado para o FFmpeg de mentira.

    As opções viram argumentos do script — `steps=20, delay=0.05`, por
    exemplo, produz uma conversão de um segundo com vinte avisos de
    andamento, tempo suficiente para o cancelamento acontecer no meio.
    """
    command = [sys.executable, str(FAKE_FFMPEG)]
    for name, value in options.items():
        command += [f"--{name}", str(value)]
    return FFmpegManager(executable=command)


def _make_source(path: Path) -> Path:
    """A origem só precisa existir: quem lê o conteúdo é o FFmpeg."""
    path.write_bytes(b"arquivo de teste")
    return path


def _leftovers(folder: Path) -> list[Path]:
    """Temporários de gravação esquecidos na pasta."""
    return [p for p in folder.iterdir() if TEMP_WRITE_SUFFIX in p.name]


class _UnavailableManager:
    """Uma máquina onde o FFmpeg não está instalado."""

    def is_available(self) -> bool:
        return False

    def available_encoders(self) -> frozenset[str]:
        return frozenset()

    def has_encoder(self, name: str) -> bool:
        return False


class _Recorder:
    """Contexto de teste: guarda o progresso e pode mandar parar depois de
    um número escolhido de avisos."""

    def __init__(self, cancel_after: int | None = None) -> None:
        self.reported: list[int] = []
        self._cancel_after = cancel_after
        self.context = TaskContext(
            on_progress=self.reported.append,
            is_cancelled=lambda: (
                self._cancel_after is not None and len(self.reported) >= self._cancel_after
            ),
        )


# --- Camada de compatibilidade -------------------------------------------


def test_audio_targets_follow_the_installed_encoders() -> None:
    """Uma compilação sem libvorbis não pode oferecer OGG: melhor não
    oferecer do que oferecer e falhar na hora de converter."""
    converter = AudioConverter(_manager(encoders="libmp3lame,pcm_s16le,flac,aac"))
    assert converter.target_formats == {"mp3", "wav", "flac", "m4a"}
    assert "ogg" not in converter.target_formats


def test_video_targets_follow_the_installed_encoders() -> None:
    converter = VideoConverter(_manager(encoders="libx264,aac"))
    assert converter.target_formats == {"mp4", "mkv"}
    assert "webm" not in converter.target_formats


def test_video_offers_both_reencoding_and_audio_extraction() -> None:
    """Um MP4 na lista tem dois caminhos, e eles não se sobrepõem."""
    assert VideoConverter(_manager()).target_formats == {"mp4", "mkv", "webm"}
    assert VideoToAudioConverter(_manager()).target_formats == {
        "mp3",
        "wav",
        "flac",
        "ogg",
        "m4a",
    }


def test_registry_routes_each_video_target_to_the_right_converter() -> None:
    """Dois conversores leem MP4; quem decide qual roda é o destino.

    Trocar o formato do vídeo e extrair a trilha sonora são operações
    diferentes, e a camada de compatibilidade precisa distingui-las sem
    ambiguidade — daí os conjuntos de destino não se cruzarem.
    """
    registry = CompatibilityRegistry()
    registry.register(VideoConverter(_manager()))
    registry.register(VideoToAudioConverter(_manager()))

    assert isinstance(registry.get_converter("mp4", "mkv"), VideoConverter)
    assert isinstance(registry.get_converter("mp4", "mp3"), VideoToAudioConverter)
    # O seletor de formato mostra as duas possibilidades juntas.
    assert registry.available_targets_for("mov") == {
        "mp4",
        "mkv",
        "webm",
        "mp3",
        "wav",
        "flac",
        "ogg",
        "m4a",
    }


def test_registry_offers_nothing_for_media_without_encoders() -> None:
    """Uma compilação do FFmpeg sem nenhum codificador de vídeo não pode
    fazer o seletor mostrar MP4 — o que existe varia de máquina para
    máquina, e o seletor precisa acompanhar."""
    registry = CompatibilityRegistry()
    registry.register(VideoConverter(_manager(encoders="pcm_s16le")))

    assert registry.available_targets_for("mp4") == set()
    assert not registry.can_convert("mp4", "mkv")


def test_ffmpeg_status_reports_the_version() -> None:
    status = _manager().status()
    assert status.available
    assert status.version == "9.9.9-fake"


# --- Registro na inicialização -------------------------------------------


def test_media_converters_are_registered_when_ffmpeg_exists() -> None:
    registry = CompatibilityRegistry()

    names = register_builtin_converters(registry, ffmpeg=_manager())

    assert any("AudioConverter" in name for name in names)
    assert any("VideoConverter" in name for name in names)
    assert registry.can_convert("mp3", "wav")
    assert registry.can_convert("mp4", "webm")
    assert registry.can_convert("mkv", "m4a")  # trilha sonora de um vídeo


def test_media_converters_are_skipped_without_ffmpeg() -> None:
    """Sem FFmpeg o aplicativo abre normalmente e apenas deixa de oferecer
    áudio e vídeo — não é um erro de inicialização."""
    registry = CompatibilityRegistry()

    names = register_builtin_converters(registry, ffmpeg=_UnavailableManager())

    assert not any("Audio" in name or "Video" in name for name in names)
    assert not registry.can_convert("mp3", "wav")
    assert registry.available_targets_for("mp4") == set()


def test_media_converters_are_skipped_without_the_needed_encoders() -> None:
    """FFmpeg presente, mas compilado sem nada que sirva: o conversor de
    vídeo não entra, e o de áudio entra oferecendo só o que dá."""
    registry = CompatibilityRegistry()

    register_builtin_converters(registry, ffmpeg=_manager(encoders="pcm_s16le"))

    assert registry.available_targets_for("mp3") == {"wav"}
    assert registry.available_targets_for("mp4") == {"wav"}
    assert not registry.can_convert("mp4", "mkv")


# --- Conversão bem-sucedida ----------------------------------------------


def test_audio_conversion_writes_the_output(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "musica.wav")
    destination = tmp_path / "musica.mp3"

    result = AudioConverter(_manager()).convert(str(source), str(destination))

    assert result.success, result.error_message
    assert destination.is_file()
    assert result.output_path == str(destination)
    assert not _leftovers(tmp_path)


def test_conversion_never_touches_the_original(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "musica.wav")
    original = source.read_bytes()

    AudioConverter(_manager()).convert(str(source), str(tmp_path / "musica.mp3"))

    assert source.read_bytes() == original


def test_conversion_reports_progress_from_inside_the_task(tmp_path: Path) -> None:
    """A barra precisa andar durante a conversão de um único arquivo:
    um vídeo de dez minutos é uma tarefa só, e ficar em 0% até o fim
    faria o aplicativo parecer travado."""
    source = _make_source(tmp_path / "video.mp4")
    recorder = _Recorder()

    result = VideoConverter(_manager(steps=5)).convert(
        str(source), str(tmp_path / "video.mkv"), recorder.context
    )

    assert result.success, result.error_message
    assert len(recorder.reported) > 1
    assert recorder.reported == sorted(recorder.reported)
    # O 100 só vem depois de o arquivo estar no lugar definitivo.
    assert recorder.reported[-1] == 100
    assert all(percent < 100 for percent in recorder.reported[:-1])


def test_audio_command_uses_the_expected_codec(tmp_path: Path) -> None:
    record = tmp_path / "argumentos.json"
    source = _make_source(tmp_path / "musica.wav")

    AudioConverter(_manager(record=record)).convert(
        str(source), str(tmp_path / "musica.mp3")
    )

    arguments = json.loads(record.read_text(encoding="utf-8"))
    assert "libmp3lame" in arguments
    # A capa do álbum é descartada: sem isso, um MP3 com capa não vira WAV.
    assert "-vn" in arguments


def test_video_command_uses_the_expected_codec(tmp_path: Path) -> None:
    record = tmp_path / "argumentos.json"
    source = _make_source(tmp_path / "video.mkv")

    VideoConverter(_manager(record=record)).convert(
        str(source), str(tmp_path / "video.mp4")
    )

    arguments = json.loads(record.read_text(encoding="utf-8"))
    assert "libx264" in arguments
    assert "+faststart" in arguments
    # A extração de áudio é que descarta o vídeo — aqui ele é o conteúdo.
    assert "-vn" not in arguments


def test_audio_extraction_drops_the_video_track(tmp_path: Path) -> None:
    record = tmp_path / "argumentos.json"
    source = _make_source(tmp_path / "aula.mp4")

    result = VideoToAudioConverter(_manager(record=record)).convert(
        str(source), str(tmp_path / "aula.mp3")
    )

    assert result.success, result.error_message
    arguments = json.loads(record.read_text(encoding="utf-8"))
    assert "-vn" in arguments
    assert "libmp3lame" in arguments


def test_temporary_file_keeps_the_target_extension(tmp_path: Path) -> None:
    """O FFmpeg descobre o formato de saída pela extensão do arquivo.

    Um temporário terminado em '.filemorph-tmp' faria toda conversão de
    mídia falhar antes de começar.
    """
    record = tmp_path / "argumentos.json"
    source = _make_source(tmp_path / "musica.wav")

    AudioConverter(_manager(record=record)).convert(
        str(source), str(tmp_path / "musica.flac")
    )

    arguments = json.loads(record.read_text(encoding="utf-8"))
    written_to = arguments[-1]
    assert written_to.endswith(".flac")
    assert TEMP_WRITE_SUFFIX in written_to


# --- Falhas ---------------------------------------------------------------


def test_failure_becomes_a_friendly_message(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "quebrado.mp3")
    destination = tmp_path / "quebrado.wav"
    manager = _manager(fail="quebrado.mp3: Invalid data found when processing input")

    result = AudioConverter(manager).convert(str(source), str(destination))

    assert not result.success
    assert "corrompido" in (result.error_message or "")
    assert "Traceback" not in (result.error_message or "")


def test_failure_leaves_nothing_behind(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "quebrado.mp3")
    destination = tmp_path / "quebrado.wav"
    manager = _manager(fail="Invalid data found when processing input")

    AudioConverter(manager).convert(str(source), str(destination))

    assert not destination.exists()
    assert not _leftovers(tmp_path)


def test_failure_preserves_an_existing_destination(tmp_path: Path) -> None:
    """Gravação atômica: o arquivo bom que já ocupava o nome de destino
    continua intacto quando a conversão falha."""
    source = _make_source(tmp_path / "musica.mp3")
    destination = tmp_path / "musica.wav"
    destination.write_bytes(b"arquivo antigo que deve sobreviver")
    manager = _manager(fail="Invalid data found when processing input")

    AudioConverter(manager).convert(str(source), str(destination))

    assert destination.read_bytes() == b"arquivo antigo que deve sobreviver"


def test_unknown_target_is_refused_without_running_ffmpeg(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "musica.mp3")

    result = AudioConverter(_manager()).convert(str(source), str(tmp_path / "x.aiff"))

    assert not result.success
    assert "aiff" in (result.error_message or "")


def test_missing_source_is_reported_clearly(tmp_path: Path) -> None:
    result = AudioConverter(_manager()).convert(
        str(tmp_path / "sumiu.mp3"), str(tmp_path / "sumiu.wav")
    )

    assert not result.success
    assert "não foi encontrado" in (result.error_message or "")


def test_refuses_to_write_over_the_source(tmp_path: Path) -> None:
    """MP3 para MP3 no mesmo arquivo: o FFmpeg nem chega a rodar."""
    record = tmp_path / "argumentos.json"
    source = _make_source(tmp_path / "musica.mp3")

    result = AudioConverter(_manager(record=record)).convert(str(source), str(source))

    assert not result.success
    assert source.read_bytes() == b"arquivo de teste"
    assert not record.exists()


def test_missing_encoder_is_refused_before_converting(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "musica.wav")
    manager = _manager(encoders="pcm_s16le")

    result = AudioConverter(manager).convert(str(source), str(tmp_path / "musica.mp3"))

    assert not result.success
    assert "libmp3lame" in (result.error_message or "")
    assert not (tmp_path / "musica.mp3").exists()


def test_converter_explains_a_missing_ffmpeg(tmp_path: Path) -> None:
    """Sem FFmpeg o conversor nem chega a ser registrado, mas se alguém o
    chamar direto a resposta ainda precisa ser uma frase, não um
    traceback."""
    source = _make_source(tmp_path / "musica.mp3")
    destination = tmp_path / "musica.wav"

    result = AudioConverter(_UnavailableManager()).convert(str(source), str(destination))

    assert not result.success
    assert "FFmpeg" in (result.error_message or "")
    assert not destination.exists()


# --- Cancelamento ---------------------------------------------------------


def test_cancelling_stops_the_running_conversion(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "longo.mp4")
    destination = tmp_path / "longo.mkv"
    recorder = _Recorder(cancel_after=2)

    with pytest.raises(OperationCancelled):
        VideoConverter(_manager(steps=40, delay=0.05)).convert(
            str(source), str(destination), recorder.context
        )

    assert recorder.reported  # parou no meio, não antes de começar


def test_cancelling_leaves_nothing_behind(tmp_path: Path) -> None:
    """O FFmpeg já tinha começado a escrever o arquivo de saída quando o
    processo foi encerrado — o que ele escreveu era um temporário, e ele
    não pode sobrar na pasta do usuário."""
    source = _make_source(tmp_path / "longo.mp4")
    destination = tmp_path / "longo.mkv"
    recorder = _Recorder(cancel_after=2)

    with pytest.raises(OperationCancelled):
        VideoConverter(_manager(steps=40, delay=0.05)).convert(
            str(source), str(destination), recorder.context
        )

    assert not destination.exists()
    assert not _leftovers(tmp_path)


def test_cancelling_preserves_an_existing_destination(tmp_path: Path) -> None:
    source = _make_source(tmp_path / "longo.mp4")
    destination = tmp_path / "longo.mkv"
    destination.write_bytes(b"conteudo antigo que deve sobreviver")
    recorder = _Recorder(cancel_after=2)

    with pytest.raises(OperationCancelled):
        VideoConverter(_manager(steps=40, delay=0.05)).convert(
            str(source), str(destination), recorder.context
        )

    assert destination.read_bytes() == b"conteudo antigo que deve sobreviver"


def test_cancelling_before_the_start_never_launches_ffmpeg(tmp_path: Path) -> None:
    record = tmp_path / "argumentos.json"
    source = _make_source(tmp_path / "longo.mp4")
    context = TaskContext(is_cancelled=lambda: True)

    with pytest.raises(OperationCancelled):
        VideoConverter(_manager(record=record)).convert(
            str(source), str(tmp_path / "longo.mkv"), context
        )

    assert not record.exists()
