"""
Módulo dedicado ao FFmpeg (item 25 do briefing).

Nas Fases 1-2, este módulo é usado apenas para a verificação de
dependências na inicialização (item 30) — ainda não há conversores de
áudio/vídeo chamando `run_command`. A execução real de comandos FFmpeg
(com captura de progresso, cancelamento de processo etc.) será
implementada na Fase 6, mas a detecção precisa existir desde já para
que o app avise honestamente o que falta, em vez de simplesmente
esconder a limitação.

Toda chamada de processo externo evita `shell=True` (item 31).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class FFmpegStatus:
    available: bool
    executable_path: str | None
    version: str | None


def detect_ffmpeg() -> FFmpegStatus:
    """Verifica se o FFmpeg está disponível no PATH e tenta ler a versão.

    Nunca lança exceção — em caso de qualquer problema, retorna
    `available=False`, para que a UI possa avisar o usuário sem
    derrubar o aplicativo (item 30: "não fechar o aplicativo
    inesperadamente").
    """
    exe_path = shutil.which("ffmpeg")
    if not exe_path:
        return FFmpegStatus(available=False, executable_path=None, version=None)

    try:
        result = subprocess.run(
            [exe_path, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
        first_line = result.stdout.splitlines()[0] if result.stdout else ""
        # Formato tipico: "ffmpeg version 6.1.1 Copyright (c) ..."
        version = first_line.replace("ffmpeg version", "").strip().split(" ")[0] or None
        return FFmpegStatus(available=True, executable_path=exe_path, version=version)
    except (subprocess.SubprocessError, OSError, IndexError):
        # O binário existe mas não respondeu como esperado — tratamos
        # como disponível, porém sem informação de versão.
        return FFmpegStatus(available=True, executable_path=exe_path, version=None)


class FFmpegManager:
    """Ponto único de acesso ao FFmpeg para todo o aplicativo.

    Responsabilidades futuras (Fase 6): executar comandos, capturar
    progresso/erros, controlar e cancelar processos em execução. Por
    ora, expõe apenas o status de disponibilidade.
    """

    def __init__(self) -> None:
        self._status: FFmpegStatus | None = None

    def status(self, force_refresh: bool = False) -> FFmpegStatus:
        if self._status is None or force_refresh:
            self._status = detect_ffmpeg()
        return self._status

    def is_available(self) -> bool:
        return self.status().available


# Instância única compartilhada pelo aplicativo.
ffmpeg_manager = FFmpegManager()
