"""
Sistema de logging do FileMorph.

Os logs registram data, operação, arquivo, erro, biblioteca utilizada e
duração — mas isso é responsabilidade de quem chama o logger (os módulos
de conversão e junção). Este módulo apenas configura *onde* e *como* os
logs são gravados.

O usuário comum nunca precisa abrir esse arquivo; ele existe para
diagnóstico técnico e é acessível pelo menu "Abrir pasta de logs".

**O arquivo é sempre gravado; o console, só quando existe.** O executável
distribuído é uma aplicação de janela (`console=False` no
`FileMorph.spec`), e nele `sys.stderr` e `sys.stdout` são `None`. Um
`StreamHandler` criado assim não tem onde escrever: cada mensagem viraria
uma falha interna do logging. Em desenvolvimento, rodando pelo terminal, o
console está lá e continua recebendo os logs.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config.settings import get_app_data_dir

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

ROOT_LOGGER_NAME = "filemorph"


def get_logs_dir() -> Path:
    logs_dir = get_app_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _console_stream():
    """O fluxo de erro do console, ou None quando o processo não tem console."""
    stream = sys.stderr
    if stream is None or not hasattr(stream, "write"):
        return None
    return stream


def setup_logging(level: int = logging.INFO, logs_dir: Path | None = None) -> logging.Logger:
    """Configura o logger raiz do FileMorph e retorna o logger principal.

    Deve ser chamado uma única vez, no início de main.py, antes de
    qualquer outro módulo emitir logs. `logs_dir` existe para os testes.
    """
    root_logger = logging.getLogger(ROOT_LOGGER_NAME)
    root_logger.setLevel(level)

    # Evita handlers duplicados se setup_logging for chamado mais de uma vez
    # (por exemplo, em testes).
    if root_logger.handlers:
        return root_logger

    log_file = (logs_dir if logs_dir is not None else get_logs_dir()) / "filemorph.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Em desenvolvimento também é útil ver os logs no console — quando há um.
    stream = _console_stream()
    if stream is not None:
        console_handler = logging.StreamHandler(stream)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    root_logger.info("Logging inicializado. Arquivo: %s", log_file)
    return root_logger


def get_logger(module_name: str) -> logging.Logger:
    """Retorna um logger filho, nomeado por módulo (ex.: 'filemorph.ui.main_window')."""
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{module_name}")
