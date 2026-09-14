"""
Configurações do FileMorph.

Responsável por carregar, expor e persistir as preferências do usuário
(pasta padrão de saída, tema, animações, comportamento do mascote,
número de processos simultâneos etc).

As configurações são salvas em JSON dentro da pasta de dados do
aplicativo (definida por `get_app_data_dir`), nunca dentro do próprio
código-fonte ou ao lado do executável — isso garante que funcione tanto
em desenvolvimento quanto empacotado, no instalador e na versão portátil.

## O arquivo é lido com desconfiança

O `settings.json` é um arquivo de texto que qualquer um pode editar, que
um programa de sincronização pode corromper e que uma queda de energia
pode deixar pela metade. Por isso cada campo é conferido ao ser lido
(`Settings.from_dict`): um valor inválido volta ao padrão *daquele campo*,
sem descartar os outros que estavam certos. Um tema "roxo" não pode
apagar a pasta de saída que o usuário escolheu.

## E gravado de forma atômica

A gravação vai para um arquivo temporário ao lado do definitivo, que só
ocupa o lugar dele (`os.replace`) depois de escrito e descarregado no
disco. Se o programa cair no meio, o que sobra é o temporário incompleto
— o `settings.json` anterior continua inteiro.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

# Variável de ambiente que troca a pasta de dados do aplicativo. Serve à
# verificação automática do executável empacotado e à suíte de testes, que
# não podem ler nem gravar as configurações e os logs de quem usa a máquina.
DATA_DIR_ENV = "FILEMORPH_DATA_DIR"

THEMES: tuple[str, ...] = ("system", "light", "dark")
MIN_CONCURRENT_TASKS = 1
MAX_CONCURRENT_TASKS = 8

_TRUE_WORDS = {"true", "1", "yes", "sim", "on"}
_FALSE_WORDS = {"false", "0", "no", "nao", "não", "off"}


def get_app_data_dir() -> Path:
    """Retorna (e cria, se necessário) a pasta de dados do FileMorph.

    No Windows, usa %APPDATA%/FileMorph. Em outros sistemas (útil para
    desenvolvimento/teste), cai em ~/.filemorph. `FILEMORPH_DATA_DIR`,
    quando definida, vence as duas.
    """
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        app_dir = Path(override)
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if not base:
            base = str(Path.home())
        app_dir = Path(base) / "FileMorph"
    else:
        app_dir = Path.home() / ".filemorph"

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def _windows_documents_dir() -> Path | None:
    """A pasta Documentos de verdade, perguntada ao Windows.

    `~/Documents` é só o lugar padrão: a pasta pode ter sido movida para
    outro disco, redirecionada pela empresa ou estar dentro do OneDrive
    (`C:\\Users\\nome\\OneDrive\\Documentos`). O Windows guarda o endereço
    real como "pasta conhecida", e é ele que o Explorer mostra como
    Documentos.
    """
    if sys.platform != "win32":  # pragma: no cover — só existe no Windows
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        # FOLDERID_Documents = {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        folder_id = _GUID(
            0xFDD39AD0,
            0x238F,
            0x46AF,
            (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
        )
        buffer = ctypes.c_wchar_p()
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_id), 0, None, ctypes.byref(buffer)
        )
        try:
            if result != 0 or not buffer.value:
                return None
            return Path(buffer.value)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(buffer)
    except (AttributeError, OSError, ValueError):  # pragma: no cover — API ausente
        return None


def get_documents_dir() -> Path:
    """A pasta Documentos do usuário, onde ela realmente estiver."""
    known = _windows_documents_dir()
    if known is not None:
        return known
    documents = Path.home() / "Documents"
    return documents if documents.exists() else Path.home()


def get_default_output_dir() -> Path:
    """Pasta padrão sugerida para arquivos convertidos: Documentos/FileMorph/Convertidos."""
    return get_documents_dir() / "FileMorph" / "Convertidos"


# --- Validação de cada campo ---------------------------------------------------
#
# Cada função devolve o valor normalizado, ou None quando ele não serve —
# e aí o campo volta ao padrão.


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
    return None


def _as_concurrency(value: Any) -> int | None:
    if isinstance(value, bool):  # em Python, True é um int — mas não é um número aqui
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, int) and MIN_CONCURRENT_TASKS <= value <= MAX_CONCURRENT_TASKS:
        return value
    return None


def _as_theme(value: Any) -> str | None:
    if isinstance(value, str) and value.strip().lower() in THEMES:
        return value.strip().lower()
    return None


def _as_folder(value: Any) -> str | None:
    """Uma pasta precisa ser um caminho completo: um caminho relativo seria
    resolvido a partir de onde o programa foi aberto, que muda conforme o
    atalho — e os arquivos iriam parar em qualquer lugar."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or "\x00" in text:
        return None
    expanded = os.path.expanduser(text)
    if not os.path.isabs(expanded):
        return None
    return os.path.normpath(expanded)


def _as_optional_path(value: Any) -> str | None:
    """Vazio vale (quer dizer "não definido"); qualquer outra coisa segue
    as regras de `_as_folder`."""
    if isinstance(value, str) and not value.strip():
        return ""
    return _as_folder(value)


@dataclass
class Settings:
    """Preferências do usuário, com valores padrão sensatos."""

    output_folder: str = field(default_factory=lambda: str(get_default_output_dir()))
    open_folder_after_finish: bool = True
    show_mascot_messages: bool = True
    animations_enabled: bool = True
    ask_before_overwrite: bool = True
    max_concurrent_tasks: int = 2
    theme: str = "system"  # "light" | "dark" | "system"
    # Um FFmpeg escolhido pelo usuário (a pasta dele ou o ffmpeg.exe). Vazio
    # é o normal: usa o que vem com o FileMorph ou o do PATH.
    ffmpeg_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "Settings":
        """Monta as configurações a partir do que veio do arquivo.

        Cada campo é conferido por conta própria: um valor inválido volta ao
        padrão daquele campo, os válidos são mantidos, e campos que o
        FileMorph não conhece são ignorados.
        """
        defaults = cls()
        if not isinstance(data, dict):
            return defaults

        values: dict[str, Any] = {}
        for item in fields(cls):
            if item.name not in data:
                continue
            validator = _VALIDATORS[item.name]
            normalized = validator(data[item.name])
            if normalized is None:
                _log_invalid(item.name, data[item.name])
                continue
            values[item.name] = normalized

        merged = defaults.to_dict()
        merged.update(values)
        return cls(**merged)


_VALIDATORS = {
    "output_folder": _as_folder,
    "open_folder_after_finish": _as_bool,
    "show_mascot_messages": _as_bool,
    "animations_enabled": _as_bool,
    "ask_before_overwrite": _as_bool,
    "max_concurrent_tasks": _as_concurrency,
    "theme": _as_theme,
    "ffmpeg_path": _as_optional_path,
}


def _log_invalid(name: str, value: Any) -> None:
    # Import tardio: o logger depende deste módulo para achar a pasta de logs.
    from app.utils.logger import get_logger

    get_logger("config.settings").warning(
        "Configuração '%s' inválida (%r); usando o valor padrão.", name, value
    )


class SettingsManager:
    """Carrega e salva as Settings em disco, expondo uma instância única.

    O caminho do arquivo é injetável para os testes.
    """

    FILENAME = "settings.json"

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else get_app_data_dir() / self.FILENAME
        self._settings = self._load()

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> Settings:
        if not self._path.exists():
            return Settings()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            # Configuração corrompida ou ilegível: usa padrões e não quebra a
            # inicialização. O arquivo fica como está até o usuário salvar
            # de novo, para quem quiser recuperá-lo à mão.
            from app.utils.logger import get_logger

            get_logger("config.settings").warning(
                "settings.json ilegível (%s); usando as configurações padrão.", exc
            )
            return Settings()
        return Settings.from_dict(data)

    def save(self) -> None:
        """Grava de forma atômica (ver o cabeçalho do módulo)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self._settings.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def update(self, **kwargs: Any) -> None:
        current = self._settings.to_dict()
        current.update(kwargs)
        self._settings = Settings.from_dict(current)
        self.save()


# Instância única compartilhada pelo aplicativo.
settings_manager = SettingsManager()
