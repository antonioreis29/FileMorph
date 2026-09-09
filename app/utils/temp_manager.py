"""
Gerenciador de arquivos temporários (item 24 do briefing).

Todo arquivo intermediário criado durante uma conversão/junção em
pipeline (ex.: JPG -> representação comum -> PDF) deve ser registrado
aqui, para que seja possível limpar tudo ao final da operação — com
sucesso ou falha — sem deixar lixo acumulado na máquina do usuário.

Ainda não há conversores reais usando isso (Fases 3+), mas a peça de
arquitetura já fica pronta, como pedido no briefing (item 3/38).
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger("utils.temp_manager")


class TempManager:
    """Cria e controla um diretório temporário exclusivo do FileMorph,
    dentro do qual cada operação recebe sua própria subpasta isolada.
    """

    def __init__(self) -> None:
        self._root = Path(tempfile.gettempdir()) / "FileMorph"
        self._root.mkdir(parents=True, exist_ok=True)
        self._registered: dict[str, list[Path]] = {}

    def new_session(self) -> str:
        """Cria uma subpasta isolada para uma operação (ex.: uma junção
        de PDFs) e retorna um id de sessão para referenciá-la depois."""
        session_id = uuid.uuid4().hex
        session_dir = self._root / session_id
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
        return self._root / session_id

    def cleanup(self, session_id: str) -> None:
        """Remove todos os arquivos registrados e a pasta da sessão.

        Tolerante a falhas: um arquivo já removido ou em uso não deve
        impedir a limpeza dos demais.
        """
        session_dir = self._root / session_id
        try:
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
            logger.debug("Sessão temporária limpa: %s", session_dir)
        except OSError as exc:
            logger.warning("Falha ao limpar sessão %s: %s", session_id, exc)
        finally:
            self._registered.pop(session_id, None)

    def cleanup_all(self) -> None:
        """Limpeza geral — útil na inicialização, para remover restos de
        uma execução anterior que tenha sido interrompida abruptamente."""
        for session_id in list(self._registered.keys()):
            self.cleanup(session_id)
        if self._root.exists():
            shutil.rmtree(self._root, ignore_errors=True)
            self._root.mkdir(parents=True, exist_ok=True)


# Instância única compartilhada pelo aplicativo.
temp_manager = TempManager()
