"""
Um FFmpeg de mentira, usado pelos testes da Fase 6.

A suíte do FileMorph não pode exigir um FFmpeg instalado na máquina que
a roda — mas também não faz sentido testar o conversor de áudio/vídeo
sem exercitar o que ele tem de próprio: ler o andamento da saída do
processo, interromper o processo no meio, traduzir uma falha e nunca
deixar arquivo pela metade.

Este script resolve isso imitando o pedaço do FFmpeg que o FileMorph
usa de fato: responde a `-version` e `-encoders`, imprime a linha de
`Duration:` no stderr, publica blocos de `-progress` no stdout e grava
o arquivo de saída. Os testes o registram como executável do
`FFmpegManager` (`[sys.executable, fake_ffmpeg.py, ...]`), de modo que
o código sob teste é exatamente o de produção — só o binário do outro
lado do cano é que é falso.

Opções próprias, sempre antes dos argumentos do FFmpeg:

    --encoders lista,separada,por,virgula   o que o `-encoders` responde
    --steps N                               quantos blocos de progresso
    --delay S                               pausa entre um bloco e outro
    --duration S                            duração anunciada da mídia
    --fail MENSAGEM                         falha com esta mensagem
    --record CAMINHO                        grava os argumentos recebidos
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

DEFAULT_ENCODERS = (
    "libmp3lame",
    "pcm_s16le",
    "flac",
    "libvorbis",
    "aac",
    "libx264",
    "libvpx-vp9",
    "libopus",
)


def main(argv: list[str]) -> int:
    encoders = list(DEFAULT_ENCODERS)
    steps = 4
    delay = 0.0
    duration = 10.0
    fail_message = None
    record_path = None

    # As opções próprias vêm todas juntas na frente, em pares.
    while argv and argv[0].startswith("--"):
        option, value, argv = argv[0], argv[1], argv[2:]
        if option == "--encoders":
            encoders = [name for name in value.split(",") if name]
        elif option == "--steps":
            steps = int(value)
        elif option == "--delay":
            delay = float(value)
        elif option == "--duration":
            duration = float(value)
        elif option == "--fail":
            fail_message = value
        elif option == "--record":
            record_path = value
        else:
            raise SystemExit(f"opção desconhecida do fake_ffmpeg: {option}")

    if "-version" in argv:
        print("ffmpeg version 9.9.9-fake Copyright (c) 2000-2026 the FFmpeg developers")
        return 0

    if "-encoders" in argv:
        print("Encoders:")
        print(" V..... = Video")
        print(" ------")
        for name in encoders:
            print(f" A....D {name}    codificador de mentira")
        return 0

    return _convert(
        argv,
        steps=steps,
        delay=delay,
        duration=duration,
        fail=fail_message,
        record=record_path,
    )


def _convert(
    argv: list[str],
    *,
    steps: int,
    delay: float,
    duration: float,
    fail: str | None,
    record: str | None,
) -> int:
    output = Path(argv[-1])

    # Só a conversão é registrada: `-version` e `-encoders` são consultas
    # internas do FileMorph, e gravá-las apagaria o que o teste quer ver.
    if record:
        Path(record).write_text(json.dumps(argv), encoding="utf-8")

    # O cabeçalho vai para o stderr, como no FFmpeg de verdade — o
    # FileMorph junta os dois canos em um só e depende de conseguir
    # distinguir a linha de duração de um bloco de progresso.
    #
    # E, também como no FFmpeg de verdade, o cabeçalho é informativo:
    # quem pedir `-loglevel error` fica sem ele. Isso é intencional aqui,
    # para que o teste de progresso quebre se alguém abaixar o nível de
    # log e, sem perceber, tirar do FileMorph a única fonte de duração
    # que resta quando o ffprobe não está instalado.
    if not _quiet(argv):
        print(f"Input #0, fake, from '{_input_of(argv)}':", file=sys.stderr, flush=True)
        print(
            f"  Duration: {_timestamp(duration)}, start: 0.000000, bitrate: 128 kb/s",
            file=sys.stderr,
            flush=True,
        )

    if fail:
        print(fail, file=sys.stderr, flush=True)
        return 1

    # Um codificador de verdade começa a escrever o arquivo de saída
    # antes de terminar. Imitar isso é o que dá sentido ao teste de
    # cancelamento: se nada fosse gravado, não haveria sobra possível.
    output.write_bytes(b"parcial")

    for step in range(1, steps + 1):
        if delay:
            time.sleep(delay)
        seconds = duration * step / steps
        print("bitrate= 128.0kbits/s")
        print(f"total_size={1024 * step}")
        print(f"out_time_us={int(seconds * 1_000_000)}")
        print(f"out_time={_timestamp(seconds)}")
        print("speed=1.0x")
        print("progress=continue", flush=True)

    output.write_bytes(b"convertido pelo fake_ffmpeg")
    print("progress=end", flush=True)
    return 0


def _quiet(argv: list[str]) -> bool:
    """True quando o nível de log pedido esconde as linhas informativas."""
    if "-loglevel" not in argv:
        return False
    return argv[argv.index("-loglevel") + 1] in ("error", "fatal", "panic", "quiet")


def _input_of(argv: list[str]) -> str:
    return argv[argv.index("-i") + 1] if "-i" in argv else "desconhecido"


def _timestamp(seconds: float) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:09.6f}"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
