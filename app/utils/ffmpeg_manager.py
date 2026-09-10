"""
Módulo dedicado ao FFmpeg (item 25 do briefing).

Nas Fases 1-5 este módulo respondia a uma única pergunta — "o FFmpeg
está instalado?" — usada apenas pela verificação de dependências. Na
Fase 6 ele vira o executor de verdade, e continua sendo o único lugar
do FileMorph que cria um processo externo.

Três responsabilidades:

1. **Detecção** (`status`): onde está o `ffmpeg`, qual a versão e se o
   `ffprobe` veio junto (ele é opcional: sem ele, a duração da mídia é
   lida do próprio relatório do FFmpeg).
2. **Inventário** (`available_encoders`): quais codificadores esta
   compilação do FFmpeg realmente tem. Nem toda build traz libx264 ou
   libvpx-vp9, e o princípio do projeto (item 37) é não oferecer o que
   falharia na hora — por isso os conversores consultam esta lista
   antes de dizer para quais formatos sabem converter.
3. **Execução** (`run`): roda o comando, traduz o andamento para a
   `TaskContext` e transforma um erro do FFmpeg em uma mensagem em
   português.

Sobre progresso e cancelamento: com `-progress pipe:1` o FFmpeg escreve
um bloco de andamento a cada meio segundo, e é entre dois desses blocos
que o pedido de parada é percebido — o mesmo cancelamento cooperativo
da Fase 5, só que o "ponto seguro" agora é uma leitura de linha em vez
de uma página de PDF. Como a saída da conversão é sempre um arquivo
temporário, encerrar o processo no meio não deixa nada pela metade na
pasta do usuário: quem chama apaga o temporário, e o arquivo de destino
final nunca chegou a ser tocado.

Este módulo é livre de Qt, como o resto de `app/core` e
`app/converters`: ele fala com a interface apenas pela `TaskContext`.

Toda chamada de processo externo evita `shell=True` (item 31).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.core.task_context import NULL_CONTEXT, OperationCancelled, TaskContext
from app.utils.logger import get_logger

logger = get_logger("utils.ffmpeg")

# No Windows um subprocesso herda o console e faria piscar uma janela
# preta a cada arquivo convertido. A flag só existe no Windows, daí o
# getattr — nos demais sistemas o valor 0 significa "sem flags".
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Linha do cabeçalho do FFmpeg: "  Duration: 00:03:21.53, start: 0.000000, ..."
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")

# Carimbo de tempo "00:00:10.240000". O sinal aparece no valor inicial
# inválido que o FFmpeg emite antes de processar o primeiro quadro.
_TIMESTAMP_RE = re.compile(r"^(-?)(\d+):(\d{2}):(\d{2}(?:\.\d+)?)$")

# Linhas do bloco `-progress` têm sempre a forma "chave=valor", com a
# chave em minúsculas. É assim que separamos progresso de mensagem de log.
_PROGRESS_KEY_RE = re.compile(r"^[a-z_]+=")

# Linha de codificador em `ffmpeg -encoders`: capacidades, nome, descrição.
_ENCODER_LINE_RE = re.compile(
    r"^\s*[VAS.][F.][S.][X.][B.][D.]\s+([A-Za-z0-9][A-Za-z0-9_.-]*)\s", re.MULTILINE
)

# Quantas linhas do relatório do FFmpeg guardar para explicar uma falha.
# O erro real quase sempre está nas últimas.
_LOG_TAIL = 25

# Tempo máximo de espera para o processo morrer depois de um cancelamento,
# antes de partir para o encerramento forçado.
_TERMINATE_TIMEOUT = 5


class FFmpegError(Exception):
    """Falha na execução do FFmpeg, já traduzida para o usuário.

    A mensagem desta exceção é escrita para ser exibida na interface: os
    conversores a repassam direto para o `ConversionResult`, e o
    relatório técnico completo fica no log (item 23).
    """


@dataclass
class FFmpegStatus:
    available: bool
    executable_path: str | None
    version: str | None
    ffprobe_path: str | None = None


# --- Leitura da saída do FFmpeg (funções puras, fáceis de testar) --------


def parse_duration(line: str) -> float | None:
    """Duração total da mídia, em segundos, lida do cabeçalho do FFmpeg.

    Serve de rede de segurança quando o `ffprobe` não está instalado:
    sem duração não há como calcular percentual, e a barra ficaria
    parada durante toda a conversão.
    """
    match = _DURATION_RE.search(line)
    if not match:  # inclui o caso "Duration: N/A"
        return None
    hours, minutes, seconds = match.groups()
    total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return total if total > 0 else None


def parse_progress(line: str) -> float | None:
    """Segundos já processados, lidos de uma linha do bloco `-progress`.

    Só `out_time_us` e `out_time` são aceitos. `out_time_ms`, apesar do
    nome, é publicado em microssegundos por compatibilidade histórica do
    FFmpeg — usar essa chave faria o progresso avançar mil vezes mais
    rápido do que deveria.
    """
    key, separator, value = line.partition("=")
    if not separator:
        return None
    key, value = key.strip(), value.strip()

    if key == "out_time_us":
        try:
            microseconds = int(value)
        except ValueError:  # o FFmpeg emite "N/A" antes do primeiro quadro
            return None
        return max(0.0, microseconds / 1_000_000)

    if key == "out_time":
        match = _TIMESTAMP_RE.match(value)
        if not match:
            return None
        sign, hours, minutes, seconds = match.groups()
        if sign:  # carimbo negativo é o valor inicial inválido
            return 0.0
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    return None


# Trechos conhecidos do relatório do FFmpeg e o que eles significam para
# quem está usando o aplicativo. A ordem importa: o primeiro que casar é
# o que vale, então os casos mais específicos vêm antes.
_ERROR_HINTS: tuple[tuple[str, str], ...] = (
    (
        "no space left",
        "Não há espaço em disco suficiente para gravar o arquivo convertido.",
    ),
    (
        "permission denied",
        "Sem permissão para ler o arquivo ou gravar na pasta de destino. "
        "Escolha outra pasta nas configurações.",
    ),
    ("no such file or directory", "O arquivo de origem não foi encontrado."),
    (
        "unknown encoder",
        "Esta instalação do FFmpeg não tem o codificador necessário para "
        "gerar este formato.",
    ),
    (
        "encoder not found",
        "Esta instalação do FFmpeg não tem o codificador necessário para "
        "gerar este formato.",
    ),
    (
        "decoder not found",
        "Esta instalação do FFmpeg não sabe ler o formato deste arquivo.",
    ),
    (
        "does not contain any stream",
        "Este arquivo não tem nenhuma faixa de áudio ou vídeo para converter.",
    ),
    (
        "output file is empty",
        "Este arquivo não tem nenhuma faixa que possa ser convertida para o "
        "formato escolhido.",
    ),
    (
        "moov atom not found",
        "Este vídeo está incompleto ou corrompido (falta o índice do arquivo).",
    ),
    ("invalid data found", "O arquivo não é uma mídia válida ou está corrompido."),
    (
        "invalid argument",
        "O FFmpeg recusou as opções desta conversão. Veja os logs para detalhes.",
    ),
)

_GENERIC_ERROR = "O FFmpeg não conseguiu converter este arquivo."


def friendly_error(log_lines: Sequence[str]) -> str:
    """Traduz o relatório técnico do FFmpeg em uma frase para o usuário.

    Quando nada é reconhecido, devolve a mensagem genérica acompanhada
    da última linha do relatório: é pouco amigável, mas é honesto e
    costuma bastar para o usuário entender (ou reportar) o problema,
    enquanto o relatório inteiro fica no log.
    """
    haystack = "\n".join(log_lines).lower()
    for needle, message in _ERROR_HINTS:
        if needle in haystack:
            return message

    for line in reversed(list(log_lines)):
        detail = line.strip()
        if detail:
            if len(detail) > 160:
                detail = detail[:157] + "..."
            return f"{_GENERIC_ERROR} ({detail})"
    return _GENERIC_ERROR


def _parse_encoders(output: str) -> set[str]:
    """Nomes dos codificadores listados por `ffmpeg -encoders`.

    As linhas úteis têm a forma ' A....D aac    AAC (Advanced Audio...)':
    seis caracteres de capacidades, o nome usado em `-c:a`/`-c:v` e a
    descrição. A legenda que abre a listagem (' V..... = Video') tem o
    mesmo formato de capacidades, e é por isso que o nome precisa casar
    com um identificador de verdade em vez de ser só "o segundo campo".
    """
    return {match.group(1) for match in _ENCODER_LINE_RE.finditer(output)}


def _read_version(command_prefix: Sequence[str]) -> str | None:
    try:
        result = subprocess.run(
            [*command_prefix, "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            shell=False,
            creationflags=_NO_WINDOW,
        )
    except (subprocess.SubprocessError, OSError):
        # O binário existe mas não respondeu como esperado — seguimos
        # tratando-o como disponível, porém sem informação de versão.
        return None
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    # Formato típico: "ffmpeg version 6.1.1 Copyright (c) ..."
    version = first_line.replace("ffmpeg version", "").strip().split(" ")[0]
    return version or None


def detect_ffmpeg() -> FFmpegStatus:
    """Verifica se o FFmpeg está disponível no PATH e tenta ler a versão.

    Nunca lança exceção — em caso de qualquer problema, retorna
    `available=False`, para que a UI possa avisar o usuário sem derrubar
    o aplicativo (item 30: "não fechar o aplicativo inesperadamente").
    """
    exe_path = shutil.which("ffmpeg")
    if not exe_path:
        return FFmpegStatus(available=False, executable_path=None, version=None)

    return FFmpegStatus(
        available=True,
        executable_path=exe_path,
        version=_read_version([exe_path]),
        ffprobe_path=shutil.which("ffprobe"),
    )


class FFmpegManager:
    """Ponto único de acesso ao FFmpeg para todo o aplicativo.

    O parâmetro `executable` existe para os testes: passando um prefixo
    de comando próprio (por exemplo `[sys.executable, 'fake_ffmpeg.py']`)
    dá para exercitar progresso, cancelamento e tratamento de erro sem
    depender de um FFmpeg instalado na máquina que roda a suíte. A
    aplicação usa a instância global, que descobre o binário sozinha.
    """

    def __init__(self, executable: Sequence[str] | None = None) -> None:
        self._override: list[str] | None = list(executable) if executable else None
        self._status: FFmpegStatus | None = None
        self._encoders: frozenset[str] | None = None

    # --- Disponibilidade --------------------------------------------------

    def status(self, force_refresh: bool = False) -> FFmpegStatus:
        if self._status is None or force_refresh:
            self._status = self._detect()
        return self._status

    def _detect(self) -> FFmpegStatus:
        if self._override is None:
            return detect_ffmpeg()
        return FFmpegStatus(
            available=True,
            executable_path=" ".join(self._override),
            version=_read_version(self._override),
            ffprobe_path=None,
        )

    def is_available(self) -> bool:
        return self.status().available

    def command_prefix(self) -> list[str] | None:
        """O começo de toda linha de comando do FFmpeg, ou None se ele não
        estiver disponível nesta máquina."""
        if self._override is not None:
            return list(self._override)
        path = self.status().executable_path
        return [path] if path else None

    # --- Inventário de codificadores --------------------------------------

    def available_encoders(self, force_refresh: bool = False) -> frozenset[str]:
        """Codificadores compilados nesta instalação do FFmpeg.

        O resultado é lido uma única vez e guardado: os conversores
        consultam esta lista a cada pergunta "posso converter X para Y?",
        e rodar um processo externo a cada consulta travaria a interface.
        """
        if self._encoders is not None and not force_refresh:
            return self._encoders

        prefix = self.command_prefix()
        if prefix is None:
            self._encoders = frozenset()
            return self._encoders

        try:
            result = subprocess.run(
                [*prefix, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                shell=False,
                creationflags=_NO_WINDOW,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("Não foi possível listar os codificadores do FFmpeg: %s", exc)
            self._encoders = frozenset()
            return self._encoders

        self._encoders = frozenset(_parse_encoders(result.stdout or ""))
        logger.debug("Codificadores disponíveis no FFmpeg: %d", len(self._encoders))
        return self._encoders

    def has_encoder(self, name: str) -> bool:
        return name in self.available_encoders()

    # --- Duração ----------------------------------------------------------

    def probe_duration(self, path: str | Path) -> float | None:
        """Duração da mídia em segundos, via `ffprobe`.

        Retorna None quando o ffprobe não está instalado ou não soube
        responder — nesse caso a duração ainda pode ser descoberta pelo
        cabeçalho que o próprio FFmpeg imprime ao começar a converter.
        """
        ffprobe = self.status().ffprobe_path
        if not ffprobe:
            return None
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                shell=False,
                creationflags=_NO_WINDOW,
            )
        except (subprocess.SubprocessError, OSError):
            return None

        if result.returncode != 0:
            return None
        try:
            duration = float((result.stdout or "").strip())
        except ValueError:
            return None
        return duration if duration > 0 else None

    # --- Execução ---------------------------------------------------------

    def run(
        self,
        arguments: Sequence[str],
        context: TaskContext | None = None,
        total_seconds: float | None = None,
    ) -> None:
        """Executa o FFmpeg reportando andamento e obedecendo ao cancelamento.

        Retorna normalmente quando a conversão termina bem. Levanta
        `FFmpegError` (com mensagem pronta para a interface) quando o
        FFmpeg falha, e `OperationCancelled` quando o usuário mandou
        parar — as duas são tratadas por quem chama, nunca chegam cruas
        até a UI.

        O progresso vai de 0 a 99: o 100 é responsabilidade do conversor,
        que só o reporta depois de mover o arquivo temporário para o nome
        definitivo. Enquanto o arquivo não está no lugar, a conversão não
        está pronta.
        """
        context = context or NULL_CONTEXT
        prefix = self.command_prefix()
        if prefix is None:
            raise FFmpegError(
                "O FFmpeg não foi encontrado nesta máquina. Instale-o e adicione "
                "a pasta 'bin' ao PATH do Windows para converter áudio e vídeo."
            )

        # As opções globais (`-progress`, `-y`, ...) vêm antes de `-i`.
        # `-nostdin` impede que o FFmpeg consuma a entrada padrão do
        # processo que o iniciou, e `-nostats` desliga a barra textual,
        # que só duplicaria o que já vem pelo `-progress`.
        #
        # O nível de log é deixado no padrão de propósito. Abaixar para
        # `-loglevel error` deixaria a saída mais limpa, mas levaria
        # junto a linha "Duration:" do cabeçalho — que é de onde vem a
        # duração da mídia quando o ffprobe não está instalado. Sem ela
        # não há percentual, e a barra ficaria parada a conversão
        # inteira. `-hide_banner` já corta o volume que importa.
        command = [
            *prefix,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-progress",
            "pipe:1",
            "-nostats",
            *arguments,
        ]

        context.check_cancelled()
        logger.debug("Executando FFmpeg: %s", " ".join(command))

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                shell=False,
                creationflags=_NO_WINDOW,
            )
        except OSError as exc:
            raise FFmpegError(f"Não foi possível iniciar o FFmpeg ({exc}).") from exc

        tail: deque[str] = deque(maxlen=_LOG_TAIL)
        duration = total_seconds
        last_percent = -1
        cancelled = False

        try:
            for raw_line in process.stdout or ():
                # Ponto seguro para parar: entre dois blocos de andamento,
                # nunca no meio de uma linha.
                if context.cancelled():
                    cancelled = True
                    break

                line = raw_line.rstrip("\r\n")
                if _PROGRESS_KEY_RE.match(line):
                    processed = parse_progress(line)
                    if processed is not None and duration:
                        percent = min(99, int(processed * 100 / duration))
                        if percent > last_percent:
                            last_percent = percent
                            context.report(percent)
                    continue

                if duration is None:
                    duration = parse_duration(line)
                if line.strip():
                    tail.append(line)
        except BaseException:
            # Qualquer coisa que interrompa a leitura (inclusive um
            # cancelamento vindo de dentro do `report`) precisa levar o
            # processo junto. Sem isto, o `wait` logo abaixo esperaria a
            # conversão inteira terminar antes de propagar o erro.
            self._terminate(process)
            raise
        finally:
            if cancelled:
                self._terminate(process)
            exit_code = process.wait()
            if process.stdout is not None:
                process.stdout.close()

        if cancelled:
            logger.info("FFmpeg interrompido a pedido do usuário.")
            raise OperationCancelled()

        if exit_code != 0:
            logger.warning(
                "FFmpeg terminou com código %s:\n%s", exit_code, "\n".join(tail)
            )
            raise FFmpegError(friendly_error(list(tail)))

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        """Encerra o processo do FFmpeg da forma mais gentil possível.

        Não há dado a preservar: a saída era um arquivo temporário que
        quem chamou vai apagar de qualquer jeito.
        """
        try:
            process.terminate()
            process.wait(timeout=_TERMINATE_TIMEOUT)
        except subprocess.TimeoutExpired:  # pragma: no cover — processo travado
            process.kill()
        except OSError:  # pragma: no cover — já tinha morrido sozinho
            pass


# Instância única compartilhada pelo aplicativo.
ffmpeg_manager = FFmpegManager()
