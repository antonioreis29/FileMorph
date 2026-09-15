"""
Verificação rápida de uma instalação do FileMorph, sem abrir janela.

    FileMorph.exe --smoke-test C:\\caminho\\relatorio.json

Serve a quem monta o instalador (`empacotar.ps1`) e ao CI: um executável que
o PyInstaller gerou sem reclamar ainda pode abrir com uma biblioteca faltando,
um plugin do Qt fora do lugar ou um recurso que não foi copiado. Aqui cada
peça é exercitada de verdade — uma imagem é convertida, um PDF é montado e
juntado, a folha de estilo é construída, a janela principal é criada — e o
resultado vai para um relatório JSON.

O executável distribuído não tem console, então nada é impresso: o que conta
é o código de saída (0 quando tudo passou) e o relatório. Nenhum arquivo do
usuário é lido ou gravado — tudo acontece numa pasta temporária própria, e as
configurações e os logs vão para a pasta temporária também, a menos que
`FILEMORPH_DATA_DIR` já aponte para outro lugar.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

SMOKE_TEST_FLAG = "--smoke-test"


class _Checks:
    """Coleta o resultado de cada verificação, sem deixar uma falha impedir
    as seguintes de rodarem."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def run(self, name: str, check: Callable[[], str | None]) -> None:
        started = time.monotonic()
        try:
            detail = check() or ""
            ok = True
        except Exception as exc:  # noqa: BLE001 — o relatório precisa de todas as falhas
            detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            ok = False
        self.items.append(
            {
                "name": name,
                "ok": ok,
                "detail": detail,
                "seconds": round(time.monotonic() - started, 3),
            }
        )

    @property
    def ok(self) -> bool:
        return bool(self.items) and all(item["ok"] for item in self.items)


def _python_dll_path() -> str | None:
    """De onde veio o interpretador que está rodando: no executável, é a DLL
    do Python dentro da pasta do FileMorph — a prova de que o Python da
    máquina não está sendo usado."""
    handle = getattr(sys, "dllhandle", None)
    if not handle or os.name != "nt":
        return None
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    ctypes.windll.kernel32.GetModuleFileNameW(ctypes.c_void_p(handle), buffer, len(buffer))
    return buffer.value or None


def run_smoke_test(argv: list[str]) -> int:
    report_path = _report_path(argv)
    work_dir = Path(tempfile.mkdtemp(prefix="filemorph-smoke-"))
    os.environ.setdefault("FILEMORPH_DATA_DIR", str(work_dir / "dados"))

    checks = _Checks()
    report: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "bundle_dir": getattr(sys, "_MEIPASS", None),
        "python_version": platform.python_version(),
        "python_dll": _python_dll_path(),
        "work_dir": str(work_dir),
    }

    try:
        _run_checks(checks, work_dir, report)
    finally:
        report["checks"] = checks.items
        report["ok"] = checks.ok
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _cleanup(work_dir)

    return 0 if checks.ok else 1


def _report_path(argv: list[str]) -> Path | None:
    try:
        index = argv.index(SMOKE_TEST_FLAG)
    except ValueError:
        return None
    if index + 1 < len(argv) and not argv[index + 1].startswith("-"):
        return Path(argv[index + 1])
    return None


def _cleanup(work_dir: Path) -> None:
    import logging
    import shutil

    if "app.utils.temp_manager" in sys.modules:
        sys.modules["app.utils.temp_manager"].temp_manager.cleanup_own()
    for handler in list(logging.getLogger("filemorph").handlers):
        handler.close()
        logging.getLogger("filemorph").removeHandler(handler)
    shutil.rmtree(work_dir, ignore_errors=True)


def _run_checks(checks: _Checks, work_dir: Path, report: dict[str, Any]) -> None:
    from app.utils.logger import setup_logging

    setup_logging(logs_dir=work_dir / "logs")

    from app.version import __version__

    report["version"] = __version__

    def register() -> str:
        from app.converters import register_builtin_converters
        from app.mergers import register_builtin_mergers
        from app.organizers import register_builtin_organizers

        names = register_builtin_converters() + register_builtin_mergers() + register_builtin_organizers()
        required = ("ImageConverter", "ImageToPdfConverter", "PdfToImageConverter", "PdfMerger", "PdfPageOrganizer")
        missing = [name for name in required if not any(name in item for item in names)]
        if missing:
            raise RuntimeError(f"Operações essenciais não registradas: {missing}")
        return ", ".join(names)

    checks.run("registro das operações", register)
    checks.run("conversão de imagem (PNG → JPG, WEBP, BMP, TIFF e GIF)", lambda: _convert_images(work_dir))
    checks.run("PDF (imagem → PDF, junção e PDF → imagem)", lambda: _pdf_round_trip(work_dir))
    checks.run("interface (estilo, recursos e janela principal)", _build_interface)


def _convert_images(work_dir: Path) -> str:
    from PIL import Image

    from app.core.processor import BatchRequest, FileProcessor
    from app.core.task_runner import SynchronousTaskQueue

    source_dir = work_dir / "entrada com espaço"
    source_dir.mkdir()
    source = source_dir / "imagem de teste ç.png"
    Image.new("RGBA", (64, 40), (172, 73, 160, 200)).save(source, format="PNG")

    queue = SynchronousTaskQueue()
    processor = FileProcessor(queue)
    output_dir = work_dir / "saída"
    targets = ("jpg", "webp", "bmp", "tiff", "gif")
    for target in targets:
        processor.convert_batch(BatchRequest([str(source)], target, str(output_dir), "copy"))

    results = [event[2] for event in queue.events if event[0] == "finished"]
    failures = [r.error_message for r in results if not r.success]
    if failures or len(results) != len(targets):
        raise RuntimeError(f"Conversões falharam: {failures or results}")
    produced = []
    for result in results:
        with Image.open(result.output_path) as image:
            if image.size != (64, 40):
                raise RuntimeError(f"Tamanho inesperado em {result.output_path}: {image.size}")
            produced.append(f"{Path(result.output_path).name} ({image.format})")
    if source.stat().st_size == 0:
        raise RuntimeError("A origem foi alterada.")
    return ", ".join(produced)


def _pdf_round_trip(work_dir: Path) -> str:
    import pymupdf
    from PIL import Image

    from app.converters.pdf_converter import ImageToPdfConverter, PdfToImageConverter
    from app.mergers.pdf_merger import PdfMerger

    folder = work_dir / "pdf"
    folder.mkdir()
    pages = []
    for index, color in enumerate(((200, 40, 40), (40, 200, 40))):
        image = folder / f"pagina{index}.png"
        Image.new("RGB", (120 + index * 60, 80), color).save(image, format="PNG")
        pdf = folder / f"pagina{index}.pdf"
        result = ImageToPdfConverter().convert(str(image), str(pdf))
        if not result.success:
            raise RuntimeError(result.error_message)
        pages.append(str(pdf))

    merged = folder / "junto.pdf"
    result = PdfMerger().merge(pages, str(merged))
    if not result.success:
        raise RuntimeError(result.error_message)
    with pymupdf.open(merged) as document:
        count = document.page_count
    if count != 2:
        raise RuntimeError(f"O PDF juntado tem {count} página(s), e não 2.")

    result = PdfToImageConverter().convert(str(merged), str(folder / "saida" / "junto.png"))
    if not result.success:
        raise RuntimeError(result.error_message)
    return f"{count} páginas juntadas e rasterizadas em {Path(result.output_path).name}"


def _build_interface() -> str:
    from PySide6 import __version__ as pyside_version
    from PySide6.QtWidgets import QApplication

    # A plataforma vem de QT_QPA_PLATFORM quando definida ("offscreen" no CI,
    # onde não há área de trabalho); sem ela, é a janela normal do Windows.
    app = QApplication.instance() or QApplication([sys.argv[0]])

    from app.ui.styles import build_stylesheet, get_palette
    from app.utils.resources import ICON_PATH, get_asset, get_mascot_file

    for theme in ("light", "dark"):
        stylesheet = build_stylesheet(get_palette(theme))
        if "QPushButton#primaryButton" not in stylesheet or "$" in stylesheet:
            raise RuntimeError(f"Folha de estilo do tema {theme} incompleta.")
    if get_asset(*ICON_PATH) is None:
        raise RuntimeError("Ícone do aplicativo ausente.")
    if get_mascot_file() is None:
        raise RuntimeError("Arte do mascote ausente.")

    from app.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    app.processEvents()
    title = window.windowTitle()
    window.close()
    window.deleteLater()
    app.processEvents()
    return f"PySide6 {pyside_version}, plataforma {app.platformName()}, janela '{title}'"
