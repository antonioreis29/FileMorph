"""
Testes do diagnóstico (`app/core/diagnostics.py` e a janela que o mostra).

O que está sendo protegido: o relatório diz a versão real do FileMorph e a
situação verdadeira dos programas externos; quando falta um deles, o
usuário fica sabendo exatamente o que ele habilita e onde baixá-lo; e as
dicas ao lado dos arquivos só aparecem quando mudam alguma coisa.

Os programas externos são de mentira: nada é detectado nem executado.
"""

from __future__ import annotations

import pytest

from app.core.diagnostics import (
    FFMPEG_FEATURES,
    LIBREOFFICE_FEATURES,
    collect_diagnostics,
    dependency_hint,
)
from app.utils.ffmpeg_manager import FFMPEG_DOWNLOAD_URL, SOURCE_BUNDLED, FFmpegStatus
from app.utils.libreoffice_manager import LIBREOFFICE_DOWNLOAD_URL, LibreOfficeStatus
from app.version import __version__


class _Manager:
    def __init__(self, status) -> None:
        self._status = status
        self.refreshed = False

    def status(self, force_refresh: bool = False):
        self.refreshed = self.refreshed or force_refresh
        return self._status


def _report(ffmpeg_status, office_status, **options):
    defaults = dict(output_folder="C:/Saida", data_dir="C:/Dados", logs_dir="C:/Dados/logs")
    defaults.update(options)
    return collect_diagnostics(
        ffmpeg=_Manager(ffmpeg_status), libreoffice=_Manager(office_status), **defaults
    )


def test_report_has_the_real_version_and_the_missing_programs() -> None:
    report = _report(FFmpegStatus(False, None, None), LibreOfficeStatus(False, None, None))

    text = report.as_text()

    assert report.app_version == __version__
    assert text.startswith(f"FileMorph {__version__}")
    assert "FFmpeg não foi encontrado" in text
    assert "LibreOffice não foi encontrado" in text
    assert "Converter DOCX (Word) em PDF" in text
    ffmpeg, office = report.dependencies
    assert ffmpeg.download_url == FFMPEG_DOWNLOAD_URL
    assert office.download_url == LIBREOFFICE_DOWNLOAD_URL
    assert ffmpeg.features == FFMPEG_FEATURES
    assert office.features == LIBREOFFICE_FEATURES


def test_bundled_ffmpeg_in_use_is_described() -> None:
    report = _report(
        FFmpegStatus(True, "C:/FileMorph/vendor/ffmpeg/ffmpeg.exe", "7.1", source=SOURCE_BUNDLED),
        LibreOfficeStatus(True, "C:/LibreOffice/program/soffice.exe", "24.2"),
        ffmpeg_active_formats={"mp3", "wav"},
        libreoffice_active=True,
    )

    ffmpeg, office = report.dependencies

    assert ffmpeg.status_text() == "FFmpeg encontrado (versão 7.1, incluído no FileMorph)."
    assert ffmpeg.offered_formats == ("MP3", "WAV")
    assert office.status_text() == "LibreOffice encontrado (versão 24.2)."
    assert "Formatos disponíveis: MP3, WAV" in report.as_text()


def test_program_installed_while_open_asks_for_a_restart() -> None:
    """Encontrado agora, mas as conversões foram registradas na abertura:
    a frase precisa dizer que falta reiniciar."""
    report = _report(
        FFmpegStatus(False, None, None),
        LibreOfficeStatus(True, "C:/LibreOffice/program/soffice.exe", "24.2"),
        libreoffice_active=False,
    )

    assert "Feche e abra o FileMorph" in report.dependencies[1].status_text()


def test_detection_is_refreshed_when_the_report_is_collected() -> None:
    ffmpeg = _Manager(FFmpegStatus(False, None, None))
    office = _Manager(LibreOfficeStatus(False, None, None))

    collect_diagnostics(
        output_folder="C:/Saida", data_dir="C:/Dados", logs_dir="C:/logs", ffmpeg=ffmpeg, libreoffice=office
    )

    assert ffmpeg.refreshed and office.refreshed


@pytest.mark.parametrize(
    "extensions, mode, ffmpeg, office, expected",
    [
        (["png", "pdf"], "convert", False, False, None),
        (["mp3"], "convert", True, False, None),
        (["mp3"], "convert", False, True, "FFmpeg"),
        (["docx"], "convert", True, False, "transformar DOCX em PDF"),
        (["docx", "xlsx"], "merge", True, False, "usar DOCX e XLSX no modo Juntar"),
        (["docx"], "organize", False, False, None),
        (["docx"], "convert", True, True, None),
    ],
)
def test_dependency_hint_only_speaks_when_it_matters(extensions, mode, ffmpeg, office, expected) -> None:
    hint = dependency_hint(extensions, mode, ffmpeg_available=ffmpeg, libreoffice_available=office)

    if expected is None:
        assert hint is None
    else:
        assert expected in hint
        assert "Diagnóstico" in hint


def test_dialog_offers_download_and_copies_the_report(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QPushButton

    from app.ui import diagnostics_dialog as dialog_module
    from app.ui.diagnostics_dialog import DiagnosticsDialog

    if not isinstance(QApplication.instance(), QApplication):
        pytest.skip("A janela precisa de uma QApplication.")

    report = _report(
        FFmpegStatus(True, "C:/ffmpeg/bin/ffmpeg.exe", "7.1", source="path"),
        LibreOfficeStatus(False, None, None),
        ffmpeg_active_formats={"mp3"},
    )
    opened: list[str] = []

    class _DesktopServices:
        @staticmethod
        def openUrl(url):  # noqa: N802 — nome do Qt
            opened.append(url.toString())

    monkeypatch.setattr(dialog_module, "QDesktopServices", _DesktopServices)
    dialog = DiagnosticsDialog(report, "C:/Dados/logs")
    try:
        office_buttons = dialog.dependency_sections["LibreOffice"].findChildren(QPushButton)
        ffmpeg_buttons = dialog.dependency_sections["FFmpeg"].findChildren(QPushButton)
        assert ffmpeg_buttons == []  # presente: nada a baixar
        assert len(office_buttons) == 1
        office_buttons[0].click()
        assert opened == [LIBREOFFICE_DOWNLOAD_URL]

        dialog.copy_to_clipboard()
        assert QGuiApplication.clipboard().text() == report.as_text()
        assert dialog.copy_button.text() == "Copiado!"
    finally:
        dialog.close()
        dialog.deleteLater()
