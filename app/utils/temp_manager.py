"""
Gerenciador de arquivos temporários.

Todo arquivo intermediário criado durante uma operação em etapas — o PDF
de uma imagem antes de entrar numa junção, a pasta onde o LibreOffice
grava, o perfil de usuário do LibreOffice — mora numa sessão deste
gerenciador, para ser apagado ao final da operação, com sucesso ou falha,
sem deixar lixo acumulado na máquina do usuário.

## Uma pasta por execução do aplicativo

A raiz é `%TEMP%\\FileMorph`, mas cada execução do FileMorph trabalha só
dentro da própria subpasta, `<pid>-<aleatório>`. Antes a raiz era
compartilhada, e cada abertura do aplicativo apagava a raiz inteira para
limpar restos de uma execução interrompida — o que, com duas janelas do
FileMorph abertas, apagava no meio da conversão os temporários que a
primeira ainda estava usando.

Agora cada instância apaga apenas o que é seu (`cleanup_own`, ligado ao
encerramento do aplicativo em `main.py`), e só remove a pasta de outra
execução quando ela é **comprovadamente órfã** (`cleanup_orphans`):

- Cada instância mantém aberta, durante toda a execução, uma trava de
  arquivo (`.lock`) dentro da própria pasta. O sistema operacional libera
  essa trava sozinho quando o processo termina — inclusive se ele for
  derrubado —, então conseguir travar o arquivo de outra pasta é a prova
  de que o dono dela não está mais rodando. Uma instância viva nunca perde
  a trava, e a pasta dela nunca é tocada.
- As pastas de versões antigas do FileMorph, que não tinham trava, só são
  removidas quando não recebem modificação há mais de `ORPHAN_MIN_AGE`.
  Uma execução antiga ainda aberta não passa tanto tempo sem gravar nada.

A raiz é injetável, para os testes nunca dependerem do `%TEMP%` real.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import IO

from app.utils.logger import get_logger

logger = get_logger("utils.temp_manager")

# Nome da pasta do FileMorph dentro do temporário do sistema.
ROOT_NAME = "FileMorph"

# Nome do arquivo de trava dentro da pasta de cada execução.
LOCK_NAME = ".lock"

# Pasta de uma execução deste FileMorph: "<pid>-<32 hex>".
_INSTANCE_DIR_RE = re.compile(r"^\d+-[0-9a-f]{32}$")

# Idade mínima, sem modificação, para uma pasta sem trava (de uma versão
# antiga) ser considerada abandonada.
ORPHAN_MIN_AGE = 24 * 60 * 60


def _try_lock(handle: IO[bytes]) -> bool:
    """Tenta travar o arquivo sem esperar. True se a trava foi obtida."""
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover — o aplicativo é distribuído para Windows
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _is_lock_released(lock_path: Path) -> bool:
    """True se o dono da trava não está mais rodando.

    Abrir e travar o arquivo de outra instância só dá certo quando ninguém
    mais o segura. O arquivo é fechado logo em seguida, o que libera a
    trava de novo.
    """
    try:
        with open(lock_path, "a+b") as handle:
            return _try_lock(handle)
    except OSError:
        # Não deu nem para abrir: em uso de um jeito que não é nosso, ou
        # sem permissão. Na dúvida, a pasta não é órfã.
        return False


class TempManager:
    """Cria e controla a pasta temporária desta execução do FileMorph,
    dentro da qual cada operação recebe sua própria subpasta isolada.

    A pasta só é criada na primeira vez que alguém precisa dela: importar o
    módulo (os testes, as ferramentas de `tools/`) não deixa nada no disco.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        base = Path(base_dir) if base_dir is not None else Path(tempfile.gettempdir())
        self._root = base / ROOT_NAME
        self._instance_name = f"{os.getpid()}-{uuid.uuid4().hex}"
        self._instance_dir = self._root / self._instance_name
        self._lock_handle: IO[bytes] | None = None
        self._registered: dict[str, list[Path]] = {}

    # --- Pasta desta execução ----------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def instance_dir(self) -> Path:
        """A pasta desta execução, criada (e travada) se ainda não existir."""
        self._ensure_instance_dir()
        return self._instance_dir

    def _ensure_instance_dir(self) -> None:
        if self._lock_handle is not None and self._instance_dir.is_dir():
            return
        self._instance_dir.mkdir(parents=True, exist_ok=True)
        if self._lock_handle is None:
            handle = open(self._instance_dir / LOCK_NAME, "a+b")
            if not _try_lock(handle):  # pragma: no cover — o nome é único
                handle.close()
                raise OSError(f"Não foi possível travar {self._instance_dir}")
            self._lock_handle = handle

    # --- Sessões --------------------------------------------------------------

    def new_session(self) -> str:
        """Cria uma subpasta isolada para uma operação (ex.: uma junção
        de PDFs) e retorna um id de sessão para referenciá-la depois."""
        session_id = uuid.uuid4().hex
        session_dir = self.instance_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        self._registered[session_id] = []
        logger.debug("Nova sessão temporária: %s", session_dir)
        return session_id

    def register(self, session_id: str, path: str | Path) -> Path:
        """Registra um arquivo intermediário pertencente à sessão, para
        que seja limpo depois. Retorna o Path para conveniência."""
        path = Path(path)
        self._registered.setdefault(session_id, []).append(path)
        return path

    def session_dir(self, session_id: str) -> Path:
        return self._instance_dir / session_id

    def cleanup(self, session_id: str) -> None:
        """Remove todos os arquivos registrados e a pasta da sessão.

        Tolerante a falhas: um arquivo já removido ou em uso não deve
        impedir a limpeza dos demais.
        """
        session_dir = self._instance_dir / session_id
        try:
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
            logger.debug("Sessão temporária limpa: %s", session_dir)
        except OSError as exc:  # pragma: no cover — rmtree já ignora erros
            logger.warning("Falha ao limpar sessão %s: %s", session_id, exc)
        finally:
            self._registered.pop(session_id, None)

    # --- Limpezas gerais ---------------------------------------------------------

    def cleanup_own(self) -> None:
        """Apaga a pasta desta execução inteira. Chamado no encerramento.

        Nunca toca em pasta de outra instância: o alvo é sempre o
        `instance_dir` desta, com nome gerado por ela mesma.
        """
        for session_id in list(self._registered):
            self.cleanup(session_id)
        if self._lock_handle is not None:
            try:
                self._lock_handle.close()
            finally:
                self._lock_handle = None
        if self._instance_dir.exists():
            shutil.rmtree(self._instance_dir, ignore_errors=True)
        logger.debug("Temporários desta execução removidos: %s", self._instance_dir)

    def cleanup_orphans(self, min_age_seconds: float = ORPHAN_MIN_AGE) -> list[Path]:
        """Remove as pastas de execuções que comprovadamente terminaram.

        Devolve as pastas removidas, para log e para os testes. Ver o
        cabeçalho do módulo para as duas regras.
        """
        removed: list[Path] = []
        try:
            entries = list(self._root.iterdir())
        except OSError:
            return removed

        now = time.time()
        for entry in entries:
            if entry == self._instance_dir or not entry.is_dir() or entry.is_symlink():
                continue
            if _INSTANCE_DIR_RE.match(entry.name):
                lock = entry / LOCK_NAME
                if lock.exists() and not _is_lock_released(lock):
                    continue  # outra instância, viva
                if not lock.exists() and not self._older_than(entry, now, min_age_seconds):
                    continue  # ainda sendo criada por outra instância
            elif not self._older_than(entry, now, min_age_seconds):
                continue  # de uma versão antiga, e recente demais
            shutil.rmtree(entry, ignore_errors=True)
            if not entry.exists():
                removed.append(entry)
        if removed:
            logger.info("Temporários abandonados removidos: %d pasta(s)", len(removed))
        return removed

    @staticmethod
    def _older_than(folder: Path, now: float, min_age_seconds: float) -> bool:
        """True se nada na pasta foi modificado nos últimos `min_age_seconds`."""
        try:
            newest = folder.stat().st_mtime
            for path in folder.rglob("*"):
                newest = max(newest, path.stat().st_mtime)
        except OSError:
            return False
        return now - newest >= min_age_seconds


# Instância única compartilhada pelo aplicativo.
temp_manager = TempManager()
