"""
Configurações do FileMorph.

Responsável por carregar, expor e persistir as preferências do usuário
(pasta padrão de saída, tema, animações, comportamento do mascote,
número de processos simultâneos etc).

As configurações são salvas em JSON dentro da pasta de dados do
aplicativo (definida por `get_app_data_dir`), nunca dentro do próprio
código-fonte — isso garante que funcione tanto em modo desenvolvimento
quanto empacotado com PyInstaller.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def get_app_data_dir() -> Path:
    """Retorna (e cria, se necessário) a pasta de dados do FileMorph.

    No Windows, usa %APPDATA%/FileMorph. Em outros sistemas (útil para
    desenvolvimento/teste), cai em ~/.filemorph.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if not base:
            base = str(Path.home())
        app_dir = Path(base) / "FileMorph"
    else:
        app_dir = Path.home() / ".filemorph"

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_default_output_dir() -> Path:
    """Pasta padrão sugerida para arquivos convertidos: Documentos/Convertidos."""
    documents = Path.home() / "Documents"
    if not documents.exists():
        documents = Path.home()
    output = documents / "FileMorph" / "Convertidos"
    return output


@dataclass
class Settings:
    """Preferências do usuário, com valores padrão sensatos.

    Ver item 26 do briefing: pasta padrão, abrir pasta ao concluir,
    mensagens do mascote, animações, confirmar substituição, número de
    processos simultâneos e tema.
    """

    output_folder: str = field(default_factory=lambda: str(get_default_output_dir()))
    open_folder_after_finish: bool = True
    show_mascot_messages: bool = True
    animations_enabled: bool = True
    ask_before_overwrite: bool = True
    max_concurrent_tasks: int = 2
    theme: str = "system"  # "light" | "dark" | "system"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        defaults = cls()
        merged = defaults.to_dict()
        merged.update({k: v for k, v in data.items() if k in merged})
        return cls(**merged)


class SettingsManager:
    """Carrega e salva as Settings em disco, expondo uma instância única."""

    FILENAME = "settings.json"

    def __init__(self) -> None:
        self._path = get_app_data_dir() / self.FILENAME
        self._settings = self._load()

    @property
    def settings(self) -> Settings:
        return self._settings

    def _load(self) -> Settings:
        if not self._path.exists():
            return Settings()
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return Settings.from_dict(data)
        except (json.JSONDecodeError, OSError):
            # Configuração corrompida ou ilegível: usa padrões e não
            # quebra a inicialização do aplicativo.
            return Settings()

    def save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._settings.to_dict(), fh, ensure_ascii=False, indent=2)

    def update(self, **kwargs: Any) -> None:
        current = self._settings.to_dict()
        current.update(kwargs)
        self._settings = Settings.from_dict(current)
        self.save()


# Instância única compartilhada pelo aplicativo.
settings_manager = SettingsManager()
