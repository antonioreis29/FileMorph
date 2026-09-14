"""
Conversores de vídeo baseados em FFmpeg.

Duas operações, cada uma em sua classe, porque são coisas diferentes
para quem usa o aplicativo:

- `VideoConverter` — troca o formato do vídeo (MP4, MKV, WEBM),
  mantendo imagem e som;
- `VideoToAudioConverter` — extrai só a trilha sonora, gravando-a como
  MP3, WAV, FLAC, OGG ou M4A. É o "tirar o áudio do vídeo", pedido
  comum o bastante para merecer existir de fato em vez de obrigar a
  duas conversões em sequência.

As duas leem os mesmos formatos de entrada e produzem conjuntos de
destino que não se cruzam, então a camada de compatibilidade nunca
fica em dúvida sobre qual conversor chamar: um MP4 na lista oferece
MP4/MKV/WEBM (troca de formato) e MP3/WAV/FLAC/OGG/M4A (extração), e a
escolha do usuário no seletor decide qual dos dois roda.

Sobre tempo de conversão: converter vídeo é recodificar quadro a
quadro, e leva na ordem de grandeza da duração do próprio vídeo — não
dos segundos que uma imagem leva. É justamente por isso que a conversão
de vídeo depende do progresso contínuo e do cancelamento: um vídeo
longo precisa mostrar que está andando, e precisa poder ser
interrompido.
"""

from __future__ import annotations

from app.converters.audio_converter import AUDIO_COMMON_ARGUMENTS, AUDIO_PROFILES
from app.converters.media_converter import MediaConverter, MediaProfile

# Contêineres de vídeo que sabemos ler. AVI e MOV entram só como
# origem: são formatos que o usuário recebe e quer converter, não
# formatos que faça sentido gerar hoje.
VIDEO_SOURCE_FORMATS: set[str] = {"mp4", "mkv", "avi", "mov", "webm"}

# Vídeo em H.264 com áudio AAC: a combinação que toca em praticamente
# qualquer lugar (Windows, celular, navegador, TV).
#
# - `-crf 23` é a qualidade padrão do x264, visualmente próxima do
#   original com um arquivo de tamanho razoável;
# - `-preset medium` é o equilíbrio entre tempo de conversão e
#   compressão;
# - `-pix_fmt yuv420p` garante que o resultado abra em players antigos e
#   em navegadores, que não lidam com os formatos de cor mais ricos que
#   o x264 escolheria sozinho a partir de algumas fontes.
_H264_AAC: tuple[str, ...] = (
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "23",
    "-pix_fmt",
    "yuv420p",
    "-c:a",
    "aac",
    "-b:a",
    "192k",
)

VIDEO_PROFILES: dict[str, MediaProfile] = {
    # `+faststart` move o índice para o começo do arquivo, para o vídeo
    # começar a tocar antes de ter sido baixado por inteiro.
    "mp4": MediaProfile(
        (*_H264_AAC, "-movflags", "+faststart"), ("libx264", "aac")
    ),
    "mkv": MediaProfile(_H264_AAC, ("libx264", "aac")),
    # WEBM é VP9 + Opus por definição do formato. `-b:v 0` é o que
    # coloca o VP9 em modo de qualidade constante (sem ele, o `-crf` é
    # ignorado); `-row-mt 1` usa todos os núcleos da máquina, porque
    # esta é de longe a conversão mais lenta das três.
    "webm": MediaProfile(
        (
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "32",
            "-b:v",
            "0",
            "-row-mt",
            "1",
            "-c:a",
            "libopus",
            "-b:a",
            "128k",
        ),
        ("libvpx-vp9", "libopus"),
    ),
}


class VideoConverter(MediaConverter):
    """Converte vídeo entre MP4, MKV e WEBM."""

    sources = VIDEO_SOURCE_FORMATS
    profiles = VIDEO_PROFILES
    produces = "vídeo"


class VideoToAudioConverter(MediaConverter):
    """Extrai a trilha sonora de um vídeo como arquivo de áudio.

    Reaproveita exatamente os mesmos perfis do conversor de áudio: o
    MP3 que sai de um vídeo tem a mesma qualidade do MP3 que sai de um
    FLAC, e um único lugar define isso.
    """

    sources = VIDEO_SOURCE_FORMATS
    profiles = AUDIO_PROFILES
    common_arguments = AUDIO_COMMON_ARGUMENTS
    produces = "áudio"
