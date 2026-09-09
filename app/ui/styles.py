"""
Identidade visual do FileMorph (item 6 do briefing).

Cartoon + moderna + minimalista + tecnológica: cantos bem arredondados,
sombras suaves (aplicadas via QGraphicsDropShadowEffect nos widgets,
não aqui), tipografia arredondada e paleta enxuta — sem gradientes
nem excesso de cor. As mesmas formas se mantêm nos três temas (item
27); só a paleta muda.

Este módulo expõe apenas texto de QSS (Qt Style Sheets) e as paletas
de cor associadas — nenhuma lógica de UI mora aqui.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    background: str
    surface: str
    surface_alt: str
    border: str
    text_primary: str
    text_secondary: str
    accent: str
    accent_hover: str
    accent_pressed: str
    success: str
    error: str
    warning: str


LIGHT_PALETTE = Palette(
    background="#F5F3FA",
    surface="#FFFFFF",
    surface_alt="#EFEBFA",
    border="#E1DCF0",
    text_primary="#2B2640",
    text_secondary="#79738F",
    accent="#7C5CFC",
    accent_hover="#6B49F5",
    accent_pressed="#5B3AE0",
    success="#33C481",
    error="#F0596B",
    warning="#F5A623",
)

DARK_PALETTE = Palette(
    background="#1B1830",
    surface="#242040",
    surface_alt="#2E294D",
    border="#3A335C",
    text_primary="#F1EEFC",
    text_secondary="#A9A2C9",
    accent="#9A7CFF",
    accent_hover="#AC91FF",
    accent_pressed="#8567F0",
    success="#3FD69A",
    error="#FF6E7F",
    warning="#FFB84D",
)


FONT_FAMILY = '"Segoe UI", "Nunito", "Comfortaa", sans-serif'


def build_stylesheet(palette: Palette) -> str:
    """Gera o QSS completo do aplicativo para uma paleta específica.

    Cantos arredondados generosos (12-18px) e ausência de bordas
    pesadas são a base do visual "cartoon amigável" pedido no item 6,
    sem cair em aparência infantil (sem cores saturadas em excesso,
    sem ícones exagerados).
    """
    return f"""
    QWidget {{
        background-color: {palette.background};
        color: {palette.text_primary};
        font-family: {FONT_FAMILY};
        font-size: 13px;
    }}

    QMainWindow {{
        background-color: {palette.background};
    }}

    QLabel#titleLabel {{
        font-size: 16px;
        font-weight: 700;
    }}

    QLabel#subtitleLabel, QLabel#hintLabel {{
        color: {palette.text_secondary};
        font-size: 12px;
    }}

    QLabel#mascotLabel {{
        color: {palette.text_secondary};
        font-size: 13px;
        font-style: italic;
    }}

    QPushButton {{
        background-color: {palette.surface_alt};
        color: {palette.text_primary};
        border: none;
        border-radius: 14px;
        padding: 8px 18px;
        font-weight: 600;
    }}

    QPushButton:hover {{
        background-color: {palette.border};
    }}

    QPushButton#primaryButton {{
        background-color: {palette.accent};
        color: white;
        border-radius: 18px;
        padding: 12px 28px;
        font-size: 14px;
        font-weight: 700;
    }}

    QPushButton#primaryButton:hover {{
        background-color: {palette.accent_hover};
    }}

    QPushButton#primaryButton:pressed {{
        background-color: {palette.accent_pressed};
    }}

    QPushButton#primaryButton:disabled {{
        background-color: {palette.border};
        color: {palette.text_secondary};
    }}

    QPushButton#modeButton {{
        background-color: transparent;
        border-radius: 12px;
        padding: 6px 20px;
        font-weight: 700;
        color: {palette.text_secondary};
    }}

    QPushButton#modeButton:checked {{
        background-color: {palette.accent};
        color: white;
    }}

    QFrame#dropArea {{
        background-color: {palette.surface};
        border: 2px dashed {palette.border};
        border-radius: 20px;
    }}

    QFrame#dropArea[dragActive="true"] {{
        border: 2px dashed {palette.accent};
        background-color: {palette.surface_alt};
    }}

    QFrame#fileCard {{
        background-color: {palette.surface};
        border-radius: 14px;
        border: 1px solid {palette.border};
    }}

    QFrame#topBar {{
        background-color: transparent;
    }}

    QScrollArea, QScrollArea > QWidget > QWidget {{
        background-color: transparent;
        border: none;
    }}

    QComboBox {{
        background-color: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 12px;
        padding: 6px 12px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {palette.surface};
        border-radius: 8px;
        border: 1px solid {palette.border};
    }}

    QProgressBar {{
        background-color: {palette.surface_alt};
        border-radius: 10px;
        text-align: center;
        height: 16px;
    }}

    QProgressBar::chunk {{
        background-color: {palette.accent};
        border-radius: 10px;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
    }}

    QScrollBar::handle:vertical {{
        background: {palette.border};
        border-radius: 4px;
    }}

    QMenuBar, QMenu {{
        background-color: {palette.surface};
    }}

    QMenu::item:selected {{
        background-color: {palette.surface_alt};
        border-radius: 6px;
    }}
    """


def resolve_theme_name(theme_setting: str) -> str:
    """Resolve 'system' para 'light' ou 'dark' de acordo com o SO.

    A detecção real de tema do sistema é feita pela UI (que tem acesso
    à QApplication/QPalette); esta função apenas centraliza o
    fallback quando a detecção não é possível.
    """
    if theme_setting in ("light", "dark"):
        return theme_setting
    return "light"


def get_palette(theme_name: str) -> Palette:
    return DARK_PALETTE if theme_name == "dark" else LIGHT_PALETTE
