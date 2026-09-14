"""
Testes da configuração do logging (`app/utils/logger.py`).

O executável distribuído não tem console: nele `sys.stderr` é `None`. O que
está sendo protegido é que, nesse cenário, o logging continue gravando no
arquivo e não crie um destino de console que não existe.
"""

from __future__ import annotations

import io
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from app.utils.logger import ROOT_LOGGER_NAME, get_logger, setup_logging


@pytest.fixture
def clean_root_logger():
    """Tira os handlers do logger do FileMorph durante o teste e os devolve
    depois, fechando os que o teste criou."""
    root = logging.getLogger(ROOT_LOGGER_NAME)
    saved_handlers, saved_level = list(root.handlers), root.level
    root.handlers.clear()
    try:
        yield root
    finally:
        for handler in list(root.handlers):
            handler.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_windowed_build_without_stderr_logs_only_to_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_root_logger: logging.Logger
) -> None:
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "stdout", None)

    setup_logging(logs_dir=tmp_path)
    get_logger("teste").warning("mensagem sem console")

    handlers = clean_root_logger.handlers
    assert len(handlers) == 1
    assert isinstance(handlers[0], RotatingFileHandler)
    handlers[0].flush()
    assert "mensagem sem console" in (tmp_path / "filemorph.log").read_text(encoding="utf-8")


def test_with_a_console_logs_go_to_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_root_logger: logging.Logger
) -> None:
    console = io.StringIO()
    monkeypatch.setattr(sys, "stderr", console)

    setup_logging(logs_dir=tmp_path)
    get_logger("teste").warning("mensagem com console")

    kinds = {type(handler) for handler in clean_root_logger.handlers}
    assert RotatingFileHandler in kinds
    assert logging.StreamHandler in kinds
    assert "mensagem com console" in console.getvalue()


def test_setup_twice_does_not_duplicate_handlers(
    tmp_path: Path, clean_root_logger: logging.Logger
) -> None:
    setup_logging(logs_dir=tmp_path)
    count = len(clean_root_logger.handlers)

    setup_logging(logs_dir=tmp_path)

    assert len(clean_root_logger.handlers) == count
