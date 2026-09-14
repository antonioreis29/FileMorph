"""
Identidade visual do FileMorph.

Cartoon + moderna + minimalista + tecnológica: cantos bem arredondados,
sombras suaves (aplicadas via QGraphicsDropShadowEffect nos widgets,
não aqui), tipografia arredondada e paleta enxuta — sem gradientes
nem excesso de cor. As mesmas formas se mantêm nos temas claro e
escuro; só a paleta muda.

As cores saem do mascote: são literalmente os tons do sprite em
`assets/mascot/`, gerado por `tools/gerar_mascote.py`. O rosa pastel do
corpo é claro demais para carregar texto, então os papéis ficam
separados — **o pastel é superfície, o ameixa saturado é interação**
(botões, progresso, foco).

Este módulo expõe as paletas de cor, a montagem da folha de estilo a
partir do modelo `filemorph.qss` e as duas funções que traduzem a paleta
para coisas que o QSS não sabe fazer (`tint`, `shadow_color`) — nenhuma
lógica de UI mora aqui.

## Duas regras que valem para o arquivo inteiro

**Nenhum rótulo pinta fundo.** A regra `QWidget` no topo do QSS existe
para dar cor à janela, mas ela alcança todo widget que não tenha regra
própria — inclusive os `QLabel`. O resultado era uma faixa da cor da
janela desenhada por cima de cada superfície: o texto da área de
arrastar e o nome de cada arquivo apareciam dentro de um retângulo
levemente fora de tom. A regra `QLabel {{ background: transparent }}`
corta isso de uma vez; quem realmente precisa de fundo (as pílulas de
status) reconquista o direito por seletor de id, que é mais específico.

**Nada de cor fixa.** Toda cor sai de um campo da `Palette`, inclusive
os tons translúcidos, que saem de `tint()`. É o que garante que os dois
temas continuem consistentes quando um deles muda.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from string import Template

from app.utils.resources import get_asset


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
    # Um tom do destaque diluído até virar superfície: trilho da barra de
    # progresso, fundo do seletor de modo, pílulas discretas. Existe como
    # campo próprio (em vez de sair de `tint`) porque nos dois temas ele é
    # escolhido a olho, e não calculado — no escuro, diluir o rosa claro
    # no fundo escuro daria um cinza sujo.
    accent_soft: str
    # Cor do texto sobre um fundo `accent`. Existe porque os dois temas
    # discordam: no claro o destaque é escuro e pede texto branco; no
    # escuro ele é um rosa claro, onde texto branco ficaria ilegível.
    # Antes isto era um "white" fixo no QSS, o que só funcionava por
    # acidente enquanto as duas paletas tinham destaques escuros.
    on_accent: str
    success: str
    error: str
    warning: str
    # Arquivo, em `assets/icons/`, da marca desenhada dentro de uma
    # caixa de seleção marcada. São dois porque a marca é desenhada
    # sobre o destaque, e o destaque de cada tema pede uma tinta
    # diferente por cima. Ausente o arquivo, a caixa marcada continua
    # sendo o quadrado preenchido — só perde o "v".
    check_asset: str
    # Arquivo, em `assets/icons/`, da seta das caixas de escolha. Estilizar
    # o botão da caixa no QSS apaga a seta nativa do Windows, então ela é
    # uma arte própria, na cor de texto secundário de cada tema. Ausente o
    # arquivo, a caixa continua funcionando — só sem a seta.
    arrow_asset: str


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
    accent_soft="#F2E0EF",
    on_accent="#FFFFFF",  # 4,99:1 sobre o destaque
    success="#2E9E6B",
    error="#D6455C",
    warning="#C97A16",
    check_asset="check-branco.svg",
    arrow_asset="seta-malva.svg",
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
    accent_soft="#453352",
    on_accent="#3A2440",  # 7,08:1 sobre o destaque
    success="#4FD9A4",
    error="#FF8090",
    warning="#FFC163",
    check_asset="check-ameixa.svg",
    arrow_asset="seta-lilas.svg",
)


FONT_FAMILY = '"Segoe UI", "Nunito", "Comfortaa", sans-serif'


def tint(hex_color: str, percent: int) -> str:
    """A mesma cor, translúcida, no formato que o QSS entende.

    Serve para as pílulas de status: um verde chapado atrás de
    "concluído" brigaria com o card, enquanto o mesmo verde a 14%
    apenas tinge a superfície — e, por ser translúcido, funciona tanto
    sobre o card claro quanto sobre o escuro, sem precisar de uma
    segunda cor por tema.
    """
    valor = hex_color.lstrip("#")
    r, g, b = (int(valor[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {percent}%)"


def shadow_color(palette: Palette) -> tuple[int, int, int]:
    """O RGB da sombra projetada sob o botão principal.

    A sombra é aplicada em Python (`QGraphicsDropShadowEffect`), porque
    o QSS do Qt não tem `box-shadow`. A cor é a do próprio destaque, e
    não um cinza: um cinza fixo, que era o que existia antes nos cards,
    vira um halo sujo no tema escuro. Tingida do destaque, a sombra lê
    como o brilho do próprio botão nos dois temas.
    """
    valor = palette.accent.lstrip("#")
    return tuple(int(valor[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


# O modelo da folha de estilo, ao lado deste módulo. Empacotado, ele é
# copiado para o mesmo lugar relativo (ver `FileMorph.spec`).
STYLESHEET_TEMPLATE = Path(__file__).with_name("filemorph.qss")


@lru_cache(maxsize=1)
def _stylesheet_template() -> Template:
    return Template(STYLESHEET_TEMPLATE.read_text(encoding="utf-8"))


def _image_rule(asset_name: str) -> str:
    """A regra `image: url(...)` de uma arte de `assets/icons/`, ou nada se
    ela não estiver instalada."""
    arte = get_asset("icons", asset_name)
    # `as_posix` porque o QSS lê a barra invertida do Windows como
    # escape, e o caminho do arquivo chegaria quebrado.
    return f"image: url({arte.as_posix()});" if arte is not None else ""


def stylesheet_values(palette: Palette) -> dict[str, str]:
    """Os valores que preenchem o modelo `filemorph.qss` para uma paleta."""
    values = {name: str(value) for name, value in asdict(palette).items()}
    values.update(
        font_family=FONT_FAMILY,
        accent_tint_16=tint(palette.accent, 16),
        success_tint_16=tint(palette.success, 16),
        error_tint_16=tint(palette.error, 16),
        warning_tint_18=tint(palette.warning, 18),
        check_image_rule=_image_rule(palette.check_asset),
        arrow_image_rule=_image_rule(palette.arrow_asset),
    )
    return values


def build_stylesheet(palette: Palette) -> str:
    """Gera o QSS completo do aplicativo para uma paleta específica.

    Cantos arredondados generosos (12-18px) e ausência de bordas
    pesadas são a base do visual "cartoon amigável", sem cair em
    aparência infantil (sem cores saturadas em excesso, sem ícones
    exagerados).

    As regras moram em `filemorph.qss`, um arquivo de QSS de verdade, e não
    num texto dentro do Python: são centenas de linhas, e escritas aqui
    cada chave precisaria ser dobrada. `substitute` (e não
    `safe_substitute`) é de propósito — um marcador sem valor é erro de
    quem editou o modelo, e precisa aparecer na hora, não virar uma cor
    faltando na tela.
    """
    return _stylesheet_template().substitute(stylesheet_values(palette))


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
