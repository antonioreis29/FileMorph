"""
Janela de configurações (item 26 do briefing).

Expõe: pasta padrão de saída, abrir pasta ao concluir, mensagens do
mascote, animações, confirmação antes de substituir, número de
processos simultâneos e tema. Persiste via `SettingsManager`.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
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
        form = QFormLayout()
        form.setSpacing(12)

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

        buttons_row = QHBoxLayout()
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
        self._manager.update(
            output_folder=self._folder_edit.text(),
            open_folder_after_finish=self._open_folder_check.isChecked(),
            show_mascot_messages=self._mascot_check.isChecked(),
            animations_enabled=self._animations_check.isChecked(),
            ask_before_overwrite=self._ask_overwrite_check.isChecked(),
            max_concurrent_tasks=self._concurrent_spin.value(),
            theme=self._theme_combo.currentData(),
        )
        self.accept()
