"""
Módulo dedicado ao LibreOffice em modo headless.

É o segundo binário externo do projeto, depois do FFmpeg, e existe por
um motivo só: **converter DOCX em PDF com fidelidade**. Um DOCX não é
um arquivo de texto — é um pacote de XML com estilos, tabelas, imagens
e quebras de página. Reimplementar esse layout em Python daria um PDF
parecido com o documento em casos simples e bem diferente dele em
qualquer documento real, e o princípio do projeto é não
oferecer uma operação que entregue menos do que o usuário espera. Quem
sabe paginar um DOCX é um processador de texto, então é um processador
de texto que faz esse trabalho.

A consequência é a mesma do FFmpeg: sem LibreOffice instalado,
`DocxToPdfConverter` nem chega a ser registrado e "PDF" desaparece do
seletor de formato para um DOCX. As outras conversões de documento
(DOCX → TXT, TXT → DOCX, TXT → PDF, PDF → TXT) são Python puro e
continuam disponíveis.

Três diferenças em relação ao `ffmpeg_manager`, todas impostas pelo
LibreOffice:

1. **Não está no PATH no Windows.** O instalador oficial não adiciona a
   pasta `program` ao PATH, então procurar só por `shutil.which` acharia
   o binário em praticamente nenhuma máquina Windows. A detecção também
   olha os diretórios de instalação conhecidos.
2. **Não publica andamento.** O FFmpeg emite um bloco de progresso a
   cada meio segundo; o `--convert-to` do LibreOffice não diz nada até
   terminar. Em vez de inventar um percentual que não corresponde a
   nada, a conversão de DOCX não reporta progresso interno — a barra
   avança quando o arquivo termina. O cancelamento continua funcionando:
   o processo é verificado a cada fração de segundo e encerrado quando o
   usuário pede para parar.
3. **Uma instância por perfil.** Dois `soffice` rodando sobre o mesmo
   perfil de usuário não se entendem: o segundo detecta o primeiro,
   entrega o pedido a ele e termina na hora, deixando quem chamou achando
   que a conversão acabou quando ela nem começou. Daí o perfil próprio
   (`-env:UserInstallation`) e o cadeado que serializa as execuções —
   ver `_RUN_LOCK`.

Como o FFmpeg, este módulo é livre de Qt e nunca usa `shell=True`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.core.task_context import NULL_CONTEXT, OperationCancelled, TaskContext
from app.utils.file_utils import get_filename
from app.utils.logger import get_logger
from app.utils.temp_manager import temp_manager

logger = get_logger("utils.libreoffice")

# No Windows um subprocesso herda o console e faria piscar uma janela
# preta a cada arquivo convertido.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Nomes do executável, na ordem em que são procurados no PATH. No Windows
# é `soffice.exe`; no Linux e no macOS, `soffice` (o `libreoffice` é um
# script que chama o mesmo binário, e serve igual).
_EXECUTABLE_NAMES = ("soffice", "libreoffice")

# Onde o instalador oficial coloca o LibreOffice no Windows. Ele não
# adiciona nada ao PATH, então sem esta lista a detecção falharia na
# máquina da maioria dos usuários. As variáveis de ambiente são lidas em
# vez de escritas à mão porque o nome de "Program Files" muda com o
# idioma do Windows.
_WINDOWS_INSTALL_HINTS = (
    ("ProgramFiles", r"LibreOffice\program\soffice.exe"),
    ("ProgramFiles(x86)", r"LibreOffice\program\soffice.exe"),
    ("ProgramW6432", r"LibreOffice\program\soffice.exe"),
    ("LOCALAPPDATA", r"Programs\LibreOffice\program\soffice.exe"),
)

# Caminhos usuais fora do Windows, para que o desenvolvimento em Linux e
# macOS funcione sem configuração.
_UNIX_INSTALL_HINTS = (
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
    "/snap/bin/libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)

# Quanto esperar entre duas verificações de "já terminou? o usuário
# cancelou?". 0,15 s deixa o cancelamento parecer imediato sem custar
# nada em CPU.
_POLL_INTERVAL = 0.15

# Teto para uma conversão. O LibreOffice é conhecido por, ocasionalmente,
# travar esperando uma caixa de diálogo que ninguém vai ver no modo
# headless — um documento corrompido é o gatilho clássico. Sem limite, a
# tarefa ficaria pendurada para sempre e o usuário não teria como saber
# por quê.
_CONVERSION_TIMEOUT = 180

# Espera pelo encerramento gentil antes de matar o processo.
_TERMINATE_TIMEOUT = 10

# Nome do arquivo onde a saída do LibreOffice é coletada, dentro da pasta
# temporária da conversão. Só é lido para explicar uma falha.
_LOG_NAME = "libreoffice.log"

# O LibreOffice aceita um pedido por perfil de usuário, e a fila do
# FileMorph pode rodar várias tarefas ao mesmo tempo. Este cadeado
# serializa as conversões: é mais lento do que o paralelo que não
# funciona, e infinitamente melhor do que dois processos disputando o
# mesmo perfil e devolvendo resultado vazio.
_RUN_LOCK = threading.Lock()


class LibreOfficeError(Exception):
    """Falha na conversão via LibreOffice, já traduzida para o usuário.

    A mensagem é escrita para ser exibida na interface; o relatório
    técnico completo fica no log.
    """


@dataclass
class LibreOfficeStatus:
    available: bool
    executable_path: str | None
    version: str | None


# Página oficial de download, oferecida quando o LibreOffice não está
# instalado. O FileMorph nunca baixa nem instala o programa sozinho.
LIBREOFFICE_DOWNLOAD_URL = "https://www.libreoffice.org/download/download-libreoffice/"


# Trechos conhecidos da saída do LibreOffice e o que eles significam para
# quem está usando o aplicativo.
_ERROR_HINTS: tuple[tuple[str, str], ...] = (
    (
        "source file could not be loaded",
        "O LibreOffice não conseguiu abrir este documento. Ele pode estar "
        "corrompido ou protegido por senha.",
    ),
    (
        "no export filter",
        "O LibreOffice desta máquina não sabe gravar este formato.",
    ),
    (
        "no such file or directory",
        "O arquivo de origem não foi encontrado.",
    ),
    (
        "permission denied",
        "Sem permissão para ler o documento ou gravar na pasta de destino. "
        "Escolha outra pasta nas configurações.",
    ),
    (
        "no space left",
        "Não há espaço em disco suficiente para gravar o arquivo convertido.",
    ),
)

_GENERIC_ERROR = "O LibreOffice não conseguiu converter este documento."


def friendly_error(output: str) -> str:
    """Traduz a saída do LibreOffice em uma frase para o usuário.

    Quando nada é reconhecido, devolve a mensagem genérica com a última
    linha do relatório: é pouco amigável, mas é honesto, e costuma bastar
    para o usuário entender (ou reportar) o problema — o relatório
    inteiro fica no log.
    """
    haystack = output.lower()
    for needle, message in _ERROR_HINTS:
        if needle in haystack:
            return message

    for line in reversed(output.splitlines()):
        detail = line.strip()
        if detail:
            if len(detail) > 160:
                detail = detail[:157] + "..."
            return f"{_GENERIC_ERROR} ({detail})"
    return _GENERIC_ERROR


def _candidate_paths() -> list[str]:
    """Todos os lugares onde o `soffice` pode estar, na ordem de busca."""
    candidates: list[str] = []

    for name in _EXECUTABLE_NAMES:
        found = shutil.which(name)
        if found:
            candidates.append(found)

    if os.name == "nt":
        for variable, relative in _WINDOWS_INSTALL_HINTS:
            base = os.environ.get(variable)
            if base:
                candidates.append(str(Path(base) / relative))
    else:
        candidates.extend(_UNIX_INSTALL_HINTS)

    return candidates


def _read_version(executable: Sequence[str]) -> str | None:
    """Versão declarada pelo LibreOffice, ou None se ele não responder.

    O `--version` do LibreOffice é rápido, mas não é garantido: algumas
    compilações do Windows não escrevem nada no stdout quando chamadas
    sem console. Não saber a versão não impede a conversão, então a falha
    aqui é silenciosa de propósito.
    """
    try:
        result = subprocess.run(
            [*executable, "--version"],
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

    lines = (result.stdout or "").strip().splitlines()
    if not lines:
        return None
    # Formato típico: "LibreOffice 7.6.4.1 420(Build:1)".
    return lines[0].replace("LibreOffice", "").strip().split(" ")[0] or None


def detect_libreoffice(
    candidates: Sequence[str] | None = None,
    read_version: Callable[[Sequence[str]], str | None] | None = None,
) -> LibreOfficeStatus:
    """Procura o LibreOffice no PATH e nos diretórios de instalação.

    Nunca lança exceção: qualquer problema vira `available=False`, para
    que o aplicativo continue abrindo normalmente sem as conversões que
    dependem dele.

    Os parâmetros existem para os testes, que não podem depender de o
    LibreOffice estar instalado na máquina que roda a suíte.
    """
    read_version = read_version or _read_version
    for candidate in candidates if candidates is not None else _candidate_paths():
        path = Path(candidate)
        try:
            if not path.is_file():
                continue
        except OSError:  # pragma: no cover — caminho inválido no sistema
            continue
        logger.debug("LibreOffice encontrado em %s", path)
        return LibreOfficeStatus(
            available=True,
            executable_path=str(path),
            version=read_version([str(path)]),
        )

    return LibreOfficeStatus(available=False, executable_path=None, version=None)


class LibreOfficeManager:
    """Ponto único de acesso ao LibreOffice para todo o aplicativo.

    O parâmetro `executable` existe para os testes: passando um prefixo
    de comando próprio (por exemplo `[sys.executable, 'fake_soffice.py']`)
    dá para exercitar a montagem do comando, o cancelamento e o
    tratamento de erro sem exigir um LibreOffice instalado na máquina que
    roda a suíte. A aplicação usa a instância global, que descobre o
    binário sozinha.
    """

    def __init__(self, executable: Sequence[str] | None = None) -> None:
        self._override: list[str] | None = list(executable) if executable else None
        self._status: LibreOfficeStatus | None = None
        self._profile_dir: Path | None = None

    # --- Disponibilidade --------------------------------------------------

    def status(self, force_refresh: bool = False) -> LibreOfficeStatus:
        if self._status is None or force_refresh:
            self._status = self._detect()
        return self._status

    def _detect(self) -> LibreOfficeStatus:
        if self._override is None:
            return detect_libreoffice()
        return LibreOfficeStatus(
            available=True,
            executable_path=" ".join(self._override),
            version=_read_version(self._override),
        )

    def is_available(self) -> bool:
        return self.status().available

    def command_prefix(self) -> list[str] | None:
        """O começo de toda linha de comando do LibreOffice, ou None se ele
        não estiver disponível nesta máquina."""
        if self._override is not None:
            return list(self._override)
        path = self.status().executable_path
        return [path] if path else None

    # --- Perfil de usuário ------------------------------------------------

    def _user_profile_url(self) -> str:
        """URL do perfil próprio que o FileMorph manda o LibreOffice usar.

        Duas razões para não usar o perfil padrão do usuário: um
        `soffice` iniciado aqui assumiria o controle da janela que a
        pessoa talvez tenha aberta (e seria encerrado junto com ela), e o
        modo headless às vezes altera configurações do perfil.

        O diretório é criado uma vez por execução do FileMorph e
        reaproveitado — montar um perfil novo custa alguns segundos, e
        pagá-los a cada arquivo de um lote seria bobagem. Ele fica na
        pasta temporária desta execução, do `temp_manager`, que é
        apagada quando o aplicativo fecha (e, se ele cair, na abertura
        seguinte): é assim que o perfil de uma execução anterior não
        fica acumulando na máquina.
        """
        if self._profile_dir is None:
            self._profile_dir = temp_manager.session_dir(temp_manager.new_session())
            logger.debug("Perfil do LibreOffice em %s", self._profile_dir)
        return self._profile_dir.as_uri()

    # --- Execução ---------------------------------------------------------

    def convert(
        self,
        source: str | Path,
        target_ext: str,
        output_dir: str | Path,
        context: TaskContext | None = None,
    ) -> Path:
        """Converte um documento e devolve o caminho do arquivo produzido.

        `output_dir` precisa ser um diretório de uso exclusivo desta
        conversão (na prática, uma sessão do `temp_manager`): o
        `--convert-to` do LibreOffice não aceita um nome de arquivo de
        saída, apenas uma pasta, e grava lá dentro usando o nome do
        documento de origem. Quem chama é que move o resultado para o
        destino definitivo — é isso que mantém a gravação atômica.

        Levanta `LibreOfficeError` (mensagem pronta para a interface)
        quando a conversão falha, e `OperationCancelled` quando o usuário
        manda parar.
        """
        context = context or NULL_CONTEXT
        source = Path(source)
        output_dir = Path(output_dir)
        prefix = self.command_prefix()

        if prefix is None:
            raise LibreOfficeError(
                "O LibreOffice não foi encontrado nesta máquina. Instale-o para "
                "converter documentos DOCX em PDF."
            )

        context.check_cancelled()
        # O comando é montado depois de pegar a vez, e não antes: o perfil
        # de usuário é criado na primeira conversão, e montá-lo fora do
        # cadeado deixaria duas tarefas simultâneas criando um perfil cada.
        self._acquire_lock(context)
        try:
            command = [
                *prefix,
                # Sem interface, sem tela de abertura, sem restaurar
                # documentos de uma sessão anterior e sem travar em arquivo
                # bloqueado: qualquer um desses vira uma janela invisível
                # esperando uma resposta que nunca chega.
                "--headless",
                "--invisible",
                "--nologo",
                "--norestore",
                "--nolockcheck",
                "--nodefault",
                f"-env:UserInstallation={self._user_profile_url()}",
                "--convert-to",
                target_ext,
                "--outdir",
                str(output_dir),
                str(source),
            ]
            output = self._run(command, output_dir / _LOG_NAME, context)
        finally:
            _RUN_LOCK.release()

        produced = self._find_output(output_dir, source, target_ext)
        if produced is None:
            # O LibreOffice é capaz de terminar com código 0 sem ter
            # gravado nada — acontece com documento corrompido. Sem esta
            # checagem, a conversão seria reportada como bem-sucedida e o
            # usuário iria procurar um arquivo que não existe.
            logger.warning(
                "LibreOffice terminou sem gravar a saída de %s:\n%s",
                get_filename(source),
                output,
            )
            raise LibreOfficeError(friendly_error(output))

        return produced

    @staticmethod
    def _acquire_lock(context: TaskContext) -> None:
        """Espera a vez desta conversão, sem deixar de ouvir o cancelamento.

        Um `acquire()` simples bloquearia a tarefa até o fim da conversão
        anterior, e o botão "Cancelar" só teria efeito depois disso.
        """
        while not _RUN_LOCK.acquire(timeout=_POLL_INTERVAL):
            context.check_cancelled()

    def _run(self, command: list[str], log_path: Path, context: TaskContext) -> str:
        """Roda o comando até o fim, obedecendo ao cancelamento.

        Devolve a saída do processo (stdout e stderr juntos), que é o
        material de diagnóstico quando algo dá errado.

        A saída vai para um arquivo e não para um `pipe` porque aqui não há
        ninguém lendo o cano enquanto o processo roda — como o LibreOffice
        não publica andamento, não existe laço de leitura, e um cano cheio
        travaria o processo até o nosso próprio limite de tempo matá-lo.
        Um arquivo não tem esse limite, e ainda é lido depois, inteiro.
        """
        logger.debug("Executando LibreOffice: %s", " ".join(command))

        try:
            sink = open(log_path, "w+", encoding="utf-8", errors="replace")
        except OSError as exc:  # pragma: no cover — pasta temporária sumiu
            raise LibreOfficeError(
                f"Não foi possível preparar a conversão ({exc})."
            ) from exc

        try:
            try:
                process = subprocess.Popen(
                    command,
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    shell=False,
                    creationflags=_NO_WINDOW,
                )
            except OSError as exc:
                raise LibreOfficeError(
                    f"Não foi possível iniciar o LibreOffice ({exc})."
                ) from exc

            deadline = time.monotonic() + _CONVERSION_TIMEOUT
            try:
                while process.poll() is None:
                    # Ponto seguro para parar: o documento final ainda está
                    # sendo escrito numa pasta temporária, então encerrar
                    # aqui não deixa nada pela metade na pasta do usuário.
                    if context.cancelled():
                        self._terminate(process)
                        logger.info("LibreOffice interrompido a pedido do usuário.")
                        raise OperationCancelled()
                    if time.monotonic() > deadline:
                        self._terminate(process)
                        raise LibreOfficeError(
                            "O LibreOffice não respondeu em tempo hábil e foi "
                            "encerrado. O documento pode estar corrompido."
                        )
                    time.sleep(_POLL_INTERVAL)
            except BaseException:
                # Qualquer outra interrupção também precisa levar o
                # processo junto, para não deixar um `soffice` órfão.
                self._terminate(process)
                raise

            sink.seek(0)
            output = sink.read()
        finally:
            sink.close()

        if process.returncode != 0:
            logger.warning(
                "LibreOffice terminou com código %s:\n%s", process.returncode, output
            )
            raise LibreOfficeError(friendly_error(output))

        return output

    @staticmethod
    def _find_output(output_dir: Path, source: Path, target_ext: str) -> Path | None:
        """Localiza o arquivo que o LibreOffice acabou de gravar.

        Ele usa o nome do documento de origem com a extensão nova, e é
        esse o caminho conferido primeiro. A varredura do diretório é a
        rede de segurança para quando o nome não sobrevive à conversão —
        um documento com caractere que o sistema de arquivos não aceita,
        por exemplo. Como o diretório é exclusivo desta conversão, o único
        arquivo com essa extensão lá dentro é o que procuramos.
        """
        expected = output_dir / f"{source.stem}.{target_ext}"
        if expected.is_file():
            return expected
        try:
            produced = sorted(output_dir.glob(f"*.{target_ext}"))
        except OSError:  # pragma: no cover — diretório sumiu no meio
            return None
        return produced[0] if produced else None

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        """Encerra o LibreOffice da forma mais gentil possível.

        Não há dado a preservar: a saída ia para uma pasta temporária que
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
libreoffice_manager = LibreOfficeManager()
