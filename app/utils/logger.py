"""
Sistema de logging do FileMorph.

Item 23 do briefing: os logs registram data, operação, arquivo, erro,
biblioteca utilizada e duração — mas isso é responsabilidade de quem
chama o logger (os módulos de conversão/junção nas próximas fases).
Este módulo apenas configura *onde* e *como* os logs são gravados.

O usuário comum nunca precisa abrir esse arquivo; ele existe para
diagnóstico técnico e é acessível via menu "Abrir pasta de logs".
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config.settings import get_app_data_dir

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logs_dir() -> Path:
    logs_dir = get_app_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configura o logger raiz do FileMorph e retorna o logger principal.

    Deve ser chamado uma única vez, no início de main.py, antes de
    qualquer outro módulo emitir logs.
    """
    logs_dir = get_logs_dir()
    log_file = logs_dir / "filemorph.log"

    root_logger = logging.getLogger("filemorph")
    root_logger.setLevel(level)

    # Evita handlers duplicados se setup_logging for chamado mais de uma vez
    # (por exemplo, em testes).
    if root_logger.handlers:
        return root_logger

    file_handler = RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root_logger.addHandler(file_handler)

    # Em desenvolvimento também é útil ver os logs no console.
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root_logger.addHandler(console_handler)

    root_logger.info("Logging inicializado. Arquivo: %s", log_file)
    return root_logger


def get_logger(module_name: str) -> logging.Logger:
    """Retorna um logger filho, nomeado por módulo (ex.: 'filemorph.ui.main_window')."""
    return logging.getLogger(f"filemorph.{module_name}")
