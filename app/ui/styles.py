"""
Identidade visual do FileMorph (item 6 do briefing).

Cartoon + moderna + minimalista + tecnológica: cantos bem arredondados,
sombras suaves (aplicadas via QGraphicsDropShadowEffect nos widgets,
não aqui), tipografia arredondada e paleta enxuta — sem gradientes
nem excesso de cor. As mesmas formas se mantêm nos três temas (item
27); só a paleta muda.

As cores saem do mascote: são literalmente os tons do sprite em
`assets/mascot/`, gerado por `tools/gerar_mascote.py`. O rosa pastel do
corpo é claro demais para carregar texto, então os papéis ficam
separados — **o pastel é superfície, o ameixa saturado é interação**
(botões, progresso, foco).

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
    # Cor do texto sobre um fundo `accent`. Existe porque os dois temas
    # discordam: no claro o destaque é escuro e pede texto branco; no
    # escuro ele é um rosa claro, onde texto branco ficaria ilegível.
    # Antes isto era um "white" fixo no QSS, o que só funcionava por
    # acidente enquanto as duas paletas tinham destaques escuros.
    on_accent: str
    success: str
    error: str
    warning: str


LIGHT_PALETTE = Palette(
    background="#FAF4F9",
    surface="#FFFFFF",
    surface_alt="#F6E9F4",
    border="#EBD6E6",
    text_primary="#4A3350",  # o mesmo ameixa do contorno do mascote
    text_secondary="#8B7189",
    accent="#AC49A0",
    accent_hover="#983E8E",
    accent_pressed="#85347C",
    on_accent="#FFFFFF",  # 4,99:1 sobre o destaque
    success="#2E9E6B",
    error="#D6455C",
    warning="#C97A16",
)

DARK_PALETTE = Palette(
    background="#241C2B",
    surface="#2F2438",
    surface_alt="#3A2D45",
    border="#493A55",
    text_primary="#F7EDF5",
    text_secondary="#B9A5B8",
    # No escuro o destaque inverte: vira o rosa do corpo do mascote, com
    # texto ameixa por cima. É o padrão de tema escuro que mantém o
    # botão legível sem apagar a cor da marca.
    accent="#E0A6D6",
    accent_hover="#EDBBE4",
    accent_pressed="#C98CBF",
    on_accent="#3A2440",  # 7,08:1 sobre o destaque
    success="#4FD9A4",
    error="#FF8090",
    warning="#FFC163",
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
        font-size: 17px;
        font-weight: 800;
    }}

    QLabel#dropTitle {{
        font-size: 14px;
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
        color: {palette.on_accent};
        border-radius: 20px;
        padding: 14px 28px;
        font-size: 13px;
        font-weight: 800;
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
        border-radius: 14px;
        padding: 7px 22px;
        font-weight: 800;
        font-size: 12px;
        color: {palette.text_secondary};
    }}

    QPushButton#modeButton:hover:!checked {{
        color: {palette.text_primary};
    }}

    QPushButton#modeButton:checked {{
        background-color: {palette.accent};
        color: {palette.on_accent};
    }}

    QFrame#dropArea {{
        background-color: {palette.surface};
        border: 2px dashed {palette.border};
        border-radius: 18px;
    }}

    QFrame#dropArea:hover {{
        border-color: {palette.accent};
    }}

    QFrame#dropArea[dragActive="true"] {{
        border: 2px dashed {palette.accent};
        background-color: {palette.surface_alt};
    }}

    QFrame#fileCard {{
        background-color: {palette.surface};
        border-radius: 12px;
        border: 1px solid {palette.border};
    }}

    QLabel#cardIcon {{
        font-size: 15px;
    }}

    QLabel#cardName {{
        font-weight: 600;
    }}

    QLabel#cardError {{
        color: {palette.error};
        font-size: 11px;
    }}

    /* O status muda de cor conforme o estado. A propriedade dinamica
       'status' e trocada em file_list.py; as cores ficam aqui, junto
       do resto da paleta, em vez de espalhadas pelo codigo da UI. */
    QLabel#cardStatus {{
        font-size: 11px;
        font-weight: 700;
    }}

    QLabel#cardStatus[status="waiting"] {{
        color: {palette.text_secondary};
    }}

    QLabel#cardStatus[status="processing"] {{
        color: {palette.accent};
    }}

    QLabel#cardStatus[status="done"] {{
        color: {palette.success};
    }}

    QLabel#cardStatus[status="error"] {{
        color: {palette.error};
    }}

    QLabel#cardStatus[status="cancelled"] {{
        color: {palette.warning};
    }}

    QPushButton#cardRemove {{
        background-color: transparent;
        color: {palette.text_secondary};
        border-radius: 12px;
        padding: 0px;
        font-size: 16px;
        font-weight: 700;
    }}

    QPushButton#cardRemove:hover {{
        background-color: {palette.surface_alt};
        color: {palette.error};
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
        border: none;
        border-radius: 5px;
        max-height: 10px;
        min-height: 10px;
    }}

    QProgressBar::chunk {{
        background-color: {palette.accent};
        border-radius: 5px;
    }}

    QPushButton#cancelButton {{
        padding: 6px 16px;
        font-size: 12px;
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
