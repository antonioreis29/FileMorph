"""
Seletor de formato de destino (item 10 do briefing).

Nunca lista uma opção que a camada de compatibilidade não confirme
como implementada. Quando não há nenhuma conversão disponível para os
arquivos atuais (situação normal nas Fases 1-2, já que nenhum
conversor está registrado), o combo mostra um placeholder claro em
vez de ficar com opções inventadas.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox

from app.core.converter import compatibility_registry

_PLACEHOLDER = "Nenhum formato disponível ainda"


class FormatSelector(QComboBox):
    format_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._available = False
        self.currentTextChanged.connect(self._on_text_changed)
        self.refresh([])

    def refresh(self, source_extensions: list[str]) -> None:
        """Recalcula as opções de destino com base nas extensões de
        origem atualmente na lista de arquivos."""
        self.blockSignals(True)
        self.clear()

        targets = compatibility_registry.available_targets_for_many(set(source_extensions))
        self._available = bool(targets) and bool(source_extensions)

        if self._available:
            for ext in sorted(targets):
                self.addItem(ext.upper(), userData=ext)
            self.setEnabled(True)
        else:
            self.addItem(_PLACEHOLDER, userData=None)
            self.setEnabled(False)

        self.blockSignals(False)

    def has_valid_selection(self) -> bool:
        return self._available and self.currentData() is not None

    def current_extension(self) -> str | None:
        return self.currentData()

    def _on_text_changed(self, _text: str) -> None:
        if self.has_valid_selection():
            self.format_selected.emit(self.current_extension())
