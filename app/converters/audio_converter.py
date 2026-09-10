"""
Conversor de áudio baseado em FFmpeg (FASE 6 do briefing).

Este é o primeiro conversor do FileMorph que depende de um binário
externo em vez de uma biblioteca Python. A consequência prática está em
`app/converters/__init__.py`: numa máquina sem FFmpeg ele simplesmente
não é registrado, e o seletor de formato continua honesto — um MP3
adicionado à lista não oferece nenhum destino, em vez de oferecer uma
conversão que falharia (item 37).

Escopo desta fase: MP3, WAV, FLAC, OGG e M4A em qualquer combinação.

Duas decisões que valem para todos os destinos:

- **A faixa de vídeo é descartada** (`-vn`). Num arquivo de áudio essa
  "faixa de vídeo" é a capa do álbum, e formatos como o WAV não têm
  onde guardá-la — sem o `-vn`, converter um MP3 com capa para WAV
  falharia. As tags de texto (título, artista, álbum) continuam sendo
  copiadas: isso o FFmpeg já faz por padrão.
- **A qualidade é alta o suficiente para a conversão não ser
  perceptivelmente destrutiva** no uso comum, seguindo a mesma escolha
  feita no conversor de imagens da Fase 3.

Lembrando que converter entre dois formatos com perdas (MP3 -> OGG,
por exemplo) sempre recodifica: não existe conversão sem perda entre
eles, em nenhuma ferramenta. Ir para WAV ou FLAC preserva tudo o que
ainda restava no arquivo de origem.
"""

from __future__ import annotations

from app.converters.media_converter import MediaConverter, MediaProfile

# Extensões de áudio que sabemos ler. É a mesma lista dos destinos
# porque qualquer combinação entre elas funciona.
AUDIO_SOURCE_FORMATS: set[str] = {"mp3", "wav", "flac", "ogg", "m4a"}

# Como gravar cada formato de áudio, e de que codificador isso depende.
#
# - mp3: `-q:a 2` é o VBR de ~190 kbps do LAME, o ponto em que o
#   arquivo ainda é pequeno e a perda deixa de ser audível no uso comum;
# - wav e flac: sem perdas — o WAV em PCM 16 bits, que é o que qualquer
#   programa do Windows abre sem reclamar;
# - ogg: `-q:a 5` é o equivalente aproximado do MP3 acima em Vorbis;
# - m4a: 192 kbps constantes no codificador AAC nativo do FFmpeg, que
#   existe em toda compilação (ao contrário do libfdk_aac, que não pode
#   ser redistribuído).
AUDIO_PROFILES: dict[str, MediaProfile] = {
    "mp3": MediaProfile(("-c:a", "libmp3lame", "-q:a", "2"), ("libmp3lame",)),
    "wav": MediaProfile(("-c:a", "pcm_s16le"), ("pcm_s16le",)),
    "flac": MediaProfile(("-c:a", "flac"), ("flac",)),
    "ogg": MediaProfile(("-c:a", "libvorbis", "-q:a", "5"), ("libvorbis",)),
    "m4a": MediaProfile(("-c:a", "aac", "-b:a", "192k"), ("aac",)),
}

# `-vn` descarta a faixa de vídeo (a capa do álbum), pelo motivo
# explicado no cabeçalho deste módulo.
AUDIO_COMMON_ARGUMENTS: tuple[str, ...] = ("-vn",)


class AudioConverter(MediaConverter):
    """Converte áudio entre MP3, WAV, FLAC, OGG e M4A."""

    sources = AUDIO_SOURCE_FORMATS
    profiles = AUDIO_PROFILES
    common_arguments = AUDIO_COMMON_ARGUMENTS
    produces = "áudio"
