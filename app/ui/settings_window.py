"""
Janela de configurações.

Expõe: pasta padrão de saída, abrir pasta ao concluir, mensagens do
mascote, animações, confirmação antes de substituir, número de
processos simultâneos e tema. Persiste via `SettingsManager`, que confere
cada valor antes de gravar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.config.settings import SettingsManager


class SettingsWindow(QDialog):
    def __init__(self, settings_manager: SettingsManager, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurações — FileMorph")
        self.setMinimumWidth(420)
        self._manager = settings_manager
        settings = settings_manager.settings

        layout = QVBoxLayout(self)
        # Respiro nas bordas: o diálogo nasce colado nos cantos, e a
        # janela principal (que tem margens de 20px) faz o contraste
        # saltar aos olhos assim que os dois aparecem juntos.
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(18)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(13)
        # Rótulo alinhado à esquerda e centrado na altura do campo: com o
        # alinhamento padrão do Windows (à direita) os rótulos ficavam em
        # uma escada, cada um começando em uma coluna diferente.
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        # Pasta padrão
        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit(settings.output_folder)
        self._browse_button = QPushButton("Escolher...")
        self._browse_button.clicked.connect(self._browse_folder)
        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(self._browse_button)
        form.addRow("Pasta padrão:", folder_row)

        # Checkboxes
        self._open_folder_check = QCheckBox("Abrir pasta após concluir")
        self._open_folder_check.setChecked(settings.open_folder_after_finish)
        form.addRow(self._open_folder_check)

        self._mascot_check = QCheckBox("Mostrar mensagens do mascote")
        self._mascot_check.setChecked(settings.show_mascot_messages)
        form.addRow(self._mascot_check)

        self._animations_check = QCheckBox("Animar o mascote")
        self._animations_check.setChecked(settings.animations_enabled)
        form.addRow(self._animations_check)

        self._ask_overwrite_check = QCheckBox("Perguntar antes de substituir arquivos")
        self._ask_overwrite_check.setChecked(settings.ask_before_overwrite)
        form.addRow(self._ask_overwrite_check)

        # Processos simultâneos
        self._concurrent_spin = QSpinBox()
        self._concurrent_spin.setRange(1, 8)
        self._concurrent_spin.setValue(settings.max_concurrent_tasks)
        form.addRow("Processos simultâneos:", self._concurrent_spin)

        # Tema
        self._theme_combo = QComboBox()
        self._theme_combo.addItem("Sistema", userData="system")
        self._theme_combo.addItem("Claro", userData="light")
        self._theme_combo.addItem("Escuro", userData="dark")
        index = self._theme_combo.findData(settings.theme)
        self._theme_combo.setCurrentIndex(max(index, 0))
        form.addRow("Tema:", self._theme_combo)

        layout.addLayout(form)
        layout.addStretch()

        divisor = QFrame()
        divisor.setObjectName("divider")
        divisor.setFixedHeight(1)
        layout.addWidget(divisor)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)
        cancel_button = QPushButton("Cancelar")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("Salvar")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save_and_close)
        buttons_row.addStretch()
        buttons_row.addWidget(cancel_button)
        buttons_row.addWidget(save_button)
        layout.addLayout(buttons_row)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Escolher pasta padrão", self._folder_edit.text())
        if folder:
            self._folder_edit.setText(folder)

    def _save_and_close(self) -> None:
        try:
            self._manager.update(
                output_folder=self._folder_edit.text(),
                open_folder_after_finish=self._open_folder_check.isChecked(),
                show_mascot_messages=self._mascot_check.isChecked(),
                animations_enabled=self._animations_check.isChecked(),
                ask_before_overwrite=self._ask_overwrite_check.isChecked(),
                max_concurrent_tasks=self._concurrent_spin.value(),
                theme=self._theme_combo.currentData(),
            )
        except OSError as exc:
            # A gravação é atômica: o arquivo anterior continua inteiro, e a
            # janela fica aberta para o usuário tentar de novo.
            QMessageBox.warning(
                self,
                "Não foi possível salvar",
                "As configurações não puderam ser gravadas "
                f"({getattr(exc, 'strerror', None) or exc}). Nada foi perdido: "
                "as configurações anteriores continuam valendo.",
            )
            return
        self.accept()
