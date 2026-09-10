"""
Ícones de tipo de arquivo para os cards da lista.

Fica no lado da UI, e não em `app/utils/`, pela mesma razão que
`mascot.py`: depende de Qt, e o pacote `utils` é mantido livre de Qt
para que os conversores continuem testáveis sem interface.

A arte vive em `assets/icons/filetypes/`, um arquivo por extensão:
`pdf.png`, `jpeg.png`, `png.svg`… **O PNG tem prioridade sobre o SVG
de mesmo nome.** É isso que torna a troca de arte um arrastar de
arquivo: largar um `pdf.png` na pasta já substitui o `pdf.svg` gerado,
sem apagar nada e sem tocar em código. Os SVGs continuam ali como o
padrão de fábrica, prontos para reaparecer se o PNG for removido.

A ordem completa de busca para uma extensão é:

1. `<extensao>.png` — a arte trazida de fora;
2. `<extensao>.svg` — o padrão gerado por `tools/gerar_icones_tipos.py`;
3. `generico.png` / `generico.svg` — para extensão sem arte própria;
4. o emoji da categoria, em `FALLBACK_EMOJI`.

**Nada aqui é obrigatório.** Se a arte não estiver lá, ou se o Qt desta
máquina tiver sido instalado sem o módulo de SVG, `icon_pixmap`
devolve None e o card volta a mostrar o emoji. Um ícone ausente nunca
impede um arquivo de ser convertido.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap

from app.core.file_validator import get_file_category
from app.utils.file_utils import get_extension
from app.utils.logger import get_logger
from app.utils.resources import get_asset

logger = get_logger("ui.file_icons")

# Relativo a `assets/`, no mesmo formato dos caminhos de
# `app/utils/resources.py`.
FILETYPES_DIR = ("icons", "filetypes")

# Altura do ícone em pixels lógicos. Acompanha a altura da linha do
# card: grande o bastante para a arte ser reconhecível, pequeno o
# bastante para não empurrar o nome do arquivo. A largura sai da
# proporção da própria imagem, que não precisa ser quadrada.
ICON_SIZE = 24

# Em que ordem procurar a arte de uma extensão. O PNG vem primeiro para
# que uma imagem trazida de fora vença o SVG gerado, sem que o SVG
# precise ser apagado.
EXTENSOES_DE_ARTE = (".png", ".svg")

# O emoji que cada categoria usava antes da arte própria. Continua
# aqui como rede de segurança, e não como decoração: é o que aparece
# se a arte sumir da instalação.
FALLBACK_EMOJI = {
    "imagem": "🖼",
    "pdf": "📕",
    "documento": "📄",
    "audio": "🎵",
    "video": "🎬",
    "planilha": "📊",
}
FALLBACK_GENERICO = "📁"


def fallback_emoji(path: str) -> str:
    """O emoji a mostrar quando não há ícone gráfico disponível."""
    return FALLBACK_EMOJI.get(get_file_category(path) or "", FALLBACK_GENERICO)


@lru_cache(maxsize=1)
def _svg_renderer_class():
    """A classe QSvgRenderer, ou None se este Qt não trouxe o QtSvg.

    O import é adiado e cacheado porque o QtSvg vem no pacote
    PySide6-Addons: uma instalação feita com o PySide6-Essentials
    isolado não o tem, e nesse caso o aplicativo deve seguir sem
    ícones em vez de não abrir.
    """
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        logger.info("QtSvg indisponivel - os cards usarao os emoji de reserva.")
        return None
    return QSvgRenderer


def _proporcao_da_tela() -> float:
    """O device pixel ratio da tela principal (2.0 num monitor 200%).

    Renderizar no tamanho lógico e deixar o Qt ampliar depois produz um
    ícone borrado nessas telas. Como a origem é vetorial, sai mais
    barato desenhar já na resolução física.
    """
    tela = QGuiApplication.primaryScreen()
    return tela.devicePixelRatio() if tela is not None else 1.0


def _render(caminho: str, lado: int, proporcao: float) -> QPixmap | None:
    renderer_cls = _svg_renderer_class()
    if renderer_cls is None:
        return None

    renderer = renderer_cls(caminho)
    if not renderer.isValid():
        logger.warning("Icone SVG invalido, ignorando: %s", caminho)
        return None

    # A folha é um retângulo em retrato, não um quadrado. Renderizar
    # num quadrado a esticaria na horizontal, então a largura é
    # derivada da proporção que o próprio SVG declara.
    natural = renderer.defaultSize()
    if natural.height() > 0:
        proporcao_svg = natural.width() / natural.height()
    else:
        proporcao_svg = 1.0

    altura = max(1, round(lado * proporcao))
    largura = max(1, round(altura * proporcao_svg))

    # Fundo transparente é obrigatório: o card tem cor própria, e uma
    # em cada tema. Um ícone com fundo opaco viraria um retângulo
    # branco no tema escuro.
    imagem = QImage(largura, altura, QImage.Format.Format_ARGB32_Premultiplied)
    imagem.fill(Qt.GlobalColor.transparent)

    painter = QPainter(imagem)
    try:
        renderer.render(painter)
    finally:
        # Sem o end() explícito o QImage segue com um pintor ativo e o
        # Qt recusa convertê-lo em QPixmap.
        painter.end()

    pixmap = QPixmap.fromImage(imagem)
    # Informa ao Qt que estes pixels valem `lado` pontos lógicos, para
    # que o ícone ocupe o mesmo espaço no layout em qualquer tela.
    pixmap.setDevicePixelRatio(proporcao)
    return pixmap


def _carregar_bitmap(caminho: str, lado: int, proporcao: float) -> QPixmap | None:
    """Carrega um PNG e o reduz à altura pedida, mantendo a proporção."""
    original = QPixmap(caminho)
    if original.isNull():
        logger.warning("Icone PNG ilegivel, ignorando: %s", caminho)
        return None

    altura = max(1, round(lado * proporcao))

    # Qual interpolação depende da direção. Ao ampliar, FastTransformation
    # é a de vizinho mais próximo, a única que preserva a borda dura do
    # pixel art — o mesmo motivo documentado em `mascot.py`. Ao reduzir,
    # que é o caso normal aqui (a arte chega bem maior que 26 px), ela
    # serrilharia, e a suave é a certa.
    if altura > original.height():
        modo = Qt.TransformationMode.FastTransformation
    else:
        modo = Qt.TransformationMode.SmoothTransformation

    pixmap = original.scaledToHeight(altura, modo)
    pixmap.setDevicePixelRatio(proporcao)
    return pixmap


def _procurar_arte(extensao: str) -> Path | None:
    """O arquivo de arte de uma extensão, ou o genérico, ou None.

    Percorre `EXTENSOES_DE_ARTE` em ordem, então um PNG vence o SVG de
    mesmo nome. Só depois de esgotar a extensão pedida é que cai no
    genérico — um `pdf.svg` presente vale mais que um `generico.png`.
    """
    for nome in (extensao, "generico"):
        for sufixo in EXTENSOES_DE_ARTE:
            caminho = get_asset(*FILETYPES_DIR, f"{nome}{sufixo}")
            if caminho is not None:
                return caminho
    return None


@lru_cache(maxsize=64)
def _pixmap_por_extensao(extensao: str, lado: int, proporcao: float) -> QPixmap | None:
    """O pixmap de uma extensão, ou o genérico, ou None.

    O cache é por (extensão, lado, proporção) e não por caminho de
    arquivo: vinte PNGs na lista carregam a mesma arte uma vez só.
    """
    caminho = _procurar_arte(extensao)
    if caminho is None:
        return None

    if caminho.suffix.lower() == ".svg":
        return _render(str(caminho), lado, proporcao)
    return _carregar_bitmap(str(caminho), lado, proporcao)


def icon_pixmap(path: str, lado: int = ICON_SIZE) -> QPixmap | None:
    """O ícone do arquivo, já no tamanho pedido, ou None se não houver.

    `lado` é em pixels lógicos — o ajuste para telas de alta densidade
    é feito aqui dentro, e quem chama não precisa saber disso.
    """
    return _pixmap_por_extensao(get_extension(path), lado, _proporcao_da_tela())
