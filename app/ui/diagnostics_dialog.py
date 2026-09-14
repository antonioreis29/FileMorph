"""
Janela de diagnóstico: versão, Windows, pastas e programas externos.

Substitui o antigo aviso "Verificar dependências". Continua dizendo se o
FFmpeg e o LibreOffice estão disponíveis, e acrescenta o que faltava para
ajudar alguém à distância: a versão real do FileMorph, o Windows, onde
ficam configurações e logs — e um botão que copia tudo isso como texto.

Quando um dos programas falta, a janela diz em uma frase o que ele habilita
e oferece a página oficial de download. O FileMorph nunca baixa nem instala
nada sozinho: quem decide instalar é o usuário.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.diagnostics import DependencyInfo, DiagnosticReport


class DiagnosticsDialog(QDialog):
    """Mostra um `DiagnosticReport` já coletado."""

    def __init__(self, report: DiagnosticReport, logs_dir: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Diagnóstico — FileMorph")
        self.setMinimumWidth(460)
        self._report = report
        self._logs_dir = logs_dir

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        title = QLabel(f"{report.app_name} {report.app_version}")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        details = QLabel(
            f"{report.windows}\n"
            f"Python {report.python}"
            + (f" · Qt {report.qt_version}" if report.qt_version else "")
            + ("" if report.packaged else " · execução pelo código-fonte")
        )
        details.setObjectName("hintLabel")
        details.setWordWrap(True)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(details)

        self.dependency_sections: dict[str, QFrame] = {}
        for dependency in report.dependencies:
            section = self._dependency_section(dependency)
            self.dependency_sections[dependency.name] = section
            layout.addWidget(section)

        folders = QLabel(
            f"Configurações: {report.data_dir}\n"
            f"Logs: {report.logs_dir}\n"
            f"Arquivos convertidos: {report.output_folder}"
        )
        folders.setObjectName("hintLabel")
        folders.setWordWrap(True)
        folders.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(folders)

        layout.addStretch()
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.copy_button = QPushButton("Copiar informações")
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        logs_button = QPushButton("Abrir pasta de logs")
        logs_button.clicked.connect(self._open_logs)
        close_button = QPushButton("Fechar")
        close_button.setObjectName("primaryButton")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(logs_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _dependency_section(self, dependency: DependencyInfo) -> QFrame:
        frame = QFrame()
        frame.setObjectName("formatCard")
        column = QVBoxLayout(frame)
        column.setContentsMargins(16, 12, 16, 12)
        column.setSpacing(6)

        header = QLabel(("✓  " if dependency.available else "✗  ") + dependency.name)
        header.setObjectName("cardName")
        column.addWidget(header)

        status = QLabel(dependency.status_text())
        status.setWordWrap(True)
        column.addWidget(status)

        if dependency.offered_formats:
            offered = QLabel("Formatos disponíveis: " + ", ".join(dependency.offered_formats))
            offered.setObjectName("hintLabel")
            offered.setWordWrap(True)
            column.addWidget(offered)

        if not dependency.available:
            needed = QLabel("Necessário para:\n• " + "\n• ".join(dependency.features))
            needed.setObjectName("hintLabel")
            needed.setWordWrap(True)
            column.addWidget(needed)

            download = QPushButton(f"Abrir a página oficial do {dependency.name}")
            download.setObjectName("linkButton")
            download.setCursor(Qt.CursorShape.PointingHandCursor)
            download.setToolTip(dependency.download_url)
            download.clicked.connect(
                lambda _checked=False, url=dependency.download_url: QDesktopServices.openUrl(QUrl(url))
            )
            row = QHBoxLayout()
            row.addWidget(download)
            row.addStretch()
            column.addLayout(row)
        return frame

    def copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setText(self._report.as_text())
        self.copy_button.setText("Copiado!")
        # Com o próprio botão como contexto: se a janela fechar antes, o Qt
        # descarta o aviso em vez de chamá-lo sobre um botão que não existe.
        QTimer.singleShot(
            1800, self.copy_button, lambda: self.copy_button.setText("Copiar informações")
        )

    def _open_logs(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._logs_dir))
