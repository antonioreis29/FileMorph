"""
O mascote da janela principal: carregamento e animação (FASE 8).

Fica no lado da UI, e não em `app/utils/`, porque depende de Qt — o
pacote `utils` é mantido livre de Qt para que os conversores possam ser
testados sem interface. A *matemática* da animação, ao contrário, é
função pura neste mesmo módulo (`pose_for`), e é testada direto, sem
abrir janela nenhuma.

Duas decisões de carregamento, ambas para tornar a troca da arte um
arrastar de arquivo em vez de uma mudança de código:

- **O nome do arquivo não importa muito.** `ditto.png` é o preferido,
  mas se ele não existir qualquer imagem na pasta serve. Assim, jogar um
  PNG baixado direto em `assets/mascot/` já funciona.
- **Nada é obrigatório.** Sem imagem, a janela abre sem a figura, em vez
  de quebrar.

## Como o mascote se move

A animação é **procedural**: não existem quadros desenhados, existe uma
única imagem sendo esticada e deslocada ao longo do tempo. A razão é a
regra acima — se a animação fossem quadros prontos, ela só funcionaria
com a arte que veio no projeto, e qualquer imagem que o usuário jogasse
na pasta voltaria a ficar estática.

O vocabulário é o de sempre em animação: **esmagar e esticar**. Cada
estado devolve uma `Pose` — quanto esticar na horizontal, na vertical, e
quanto deslocar — e o desenho é ancorado na **base** da figura, para o
mascote parecer apoiado no chão em vez de flutuar enquanto se deforma. O
esmagamento **conserva a área** (encurtar 10% alarga 10%), que é o que
faz o olho ler "massinha elástica" em vez de "imagem redimensionada".

**Não há rotação em lugar nenhum**, e isso é deliberado: girar pixel art
em ângulo qualquer borra a borda dura de cada pixel, que é justamente o
que dá o estilo. Balanço lateral faz o mesmo serviço sem esse custo.

Se a imagem da pasta for um GIF animado, ele é reproduzido de verdade
(quadro a quadro) e a pose continua sendo aplicada por cima — a pose é o
que comunica o *estado* do aplicativo, coisa que um GIF pronto não tem
como saber.

A animação inteira obedece à opção "Animações" das configurações:
desligada, o mascote fica parado na pose neutra e o temporizador nem
roda. É o mesmo respeito que se deve a quem prefere uma interface sem
movimento.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QMovie, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from app.utils.logger import get_logger
from app.utils.resources import MASCOT_PATH, get_asset, get_assets_dir

logger = get_logger("ui.mascot")

# Formatos que o Qt lê sem plugin extra.
_EXTENSOES = (".png", ".webp", ".gif", ".jpg", ".jpeg", ".bmp")


# --- Estados -------------------------------------------------------------


class MascotState(Enum):
    """O que o mascote está fazendo.

    Os três primeiros são estados *contínuos*: valem até alguém trocá-los.
    Os três últimos são *reações*: têm duração e, ao terminar, o mascote
    volta ao estado contínuo em que estava.
    """

    IDLE = "idle"  # esperando arquivos
    READY = "ready"  # tem arquivo na lista
    WORKING = "working"  # convertendo
    HAPPY = "happy"  # terminou bem
    SAD = "sad"  # deu erro
    CANCELLED = "cancelled"  # o usuário parou


# Respiração de cada estado contínuo: (período em segundos, amplitude).
# Período menor e amplitude maior = mais agitado. Os números são pequenos
# de propósito: uma animação permanente no canto da tela tem que ser
# discreta o suficiente para ninguém se irritar depois de dez minutos.
_BREATHING = {
    MascotState.IDLE: (3.0, 0.035),
    MascotState.READY: (1.8, 0.055),
    MascotState.WORKING: (0.55, 0.085),
}

# Quanto o mascote balança para os lados enquanto trabalha, em fração da
# própria largura. É o que diferencia "trabalhando" de "só respirando
# rápido".
_WORKING_SWAY = 0.045

# Duração das reações, em segundos.
_DURATIONS = {
    MascotState.HAPPY: 1.15,
    MascotState.SAD: 0.9,
    MascotState.CANCELLED: 0.9,
}

# Altura máxima do pulo da comemoração, em fração da altura da figura.
_HAPPY_LIFT = 0.22

# Quantos pulos a comemoração dá antes de assentar.
_HAPPY_HOPS = 2

# Amplitude do "não" com a cabeça no erro, em fração da largura.
_SAD_SHAKE = 0.055

# Quantas idas e voltas esse "não" tem.
_SAD_SHAKES = 4

# O quanto o mascote murcha ao ser interrompido.
_CANCELLED_DEFLATE = 0.09


@dataclass(frozen=True)
class Pose:
    """Como desenhar a figura neste instante.

    `scale_x` e `scale_y` multiplicam o tamanho da imagem; `offset_x` e
    `offset_y` deslocam o desenho em fração da **altura** da figura (usar
    a mesma medida nos dois eixos evita que a animação mude de caráter
    quando a arte é mais larga que alta). `offset_y` negativo sobe.
    """

    scale_x: float = 1.0
    scale_y: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0


NEUTRAL_POSE = Pose()


def _squash(amount: float) -> tuple[float, float]:
    """Esmagamento que conserva a área.

    `amount` positivo achata (mais baixo e mais largo); negativo estica.
    Multiplicar a largura pelo inverso exato da altura é o que mantém a
    "quantidade de massinha" constante — sem isso a figura parece crescer
    e encolher, não se deformar.
    """
    scale_y = max(0.1, 1.0 - amount)
    return 1.0 / scale_y, scale_y


def _breathe(elapsed: float, period: float, amplitude: float) -> Pose:
    """Respiração: um seno lento entre esticado e esmagado."""
    amount = amplitude * math.sin(2 * math.pi * elapsed / period)
    scale_x, scale_y = _squash(amount)
    return Pose(scale_x=scale_x, scale_y=scale_y)


def _happy(progress: float) -> Pose:
    """Comemoração: pulos que vão diminuindo até assentar.

    A figura estica ao subir, como manda o manual: um corpo no ar é mais
    alto e mais estreito do que em repouso. Na volta ao chão a altura é
    zero e a pose é a neutra, então a aterrissagem não precisa de caso
    próprio.
    """
    decay = 1.0 - progress
    lift = abs(math.sin(math.pi * _HAPPY_HOPS * progress)) * _HAPPY_LIFT * decay
    scale_x, scale_y = _squash(-lift * 0.8)
    return Pose(scale_x=scale_x, scale_y=scale_y, offset_y=-lift)


def _sad(progress: float) -> Pose:
    """Erro: um "não" com a cabeça, murchando um pouco, que vai passando."""
    decay = 1.0 - progress
    offset_x = math.sin(2 * math.pi * _SAD_SHAKES * progress) * _SAD_SHAKE * decay
    scale_x, scale_y = _squash(0.05 * decay)
    return Pose(scale_x=scale_x, scale_y=scale_y, offset_x=offset_x)


def _cancelled(progress: float) -> Pose:
    """Interrompido: murcha e volta, como um suspiro."""
    amount = _CANCELLED_DEFLATE * math.sin(math.pi * progress)
    scale_x, scale_y = _squash(amount)
    return Pose(scale_x=scale_x, scale_y=scale_y)


def duration_of(state: MascotState) -> float | None:
    """Quanto tempo a reação dura, ou None se o estado é contínuo."""
    return _DURATIONS.get(state)


def pose_for(state: MascotState, elapsed: float) -> Pose:
    """A pose de um estado num instante, contando do início dele.

    É função pura de propósito: é onde mora todo o comportamento visível
    da animação, e é ela que os testes verificam — sem abrir janela,
    sem depender de temporizador, sem depender de relógio.
    """
    elapsed = max(0.0, elapsed)

    breathing = _BREATHING.get(state)
    if breathing is not None:
        period, amplitude = breathing
        pose = _breathe(elapsed, period, amplitude)
        if state is MascotState.WORKING:
            # O balanço tem o dobro do período da respiração, senão os
            # dois movimentos andam juntos e viram um só.
            sway = math.sin(math.pi * elapsed / period) * _WORKING_SWAY
            pose = Pose(pose.scale_x, pose.scale_y, sway, pose.offset_y)
        return pose

    duration = _DURATIONS[state]
    progress = min(1.0, elapsed / duration)
    if state is MascotState.HAPPY:
        return _happy(progress)
    if state is MascotState.SAD:
        return _sad(progress)
    return _cancelled(progress)


# --- Carregamento da arte -------------------------------------------------


def find_mascot_file() -> Path | None:
    """O arquivo do mascote: `ditto.png` se existir, senão a primeira
    imagem que estiver na pasta."""
    preferido = get_asset(*MASCOT_PATH)
    if preferido is not None:
        return preferido

    pasta = get_assets_dir() / MASCOT_PATH[0]
    if not pasta.is_dir():
        return None

    candidatos = sorted(
        p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() in _EXTENSOES
    )
    if candidatos:
        logger.info(
            "Usando '%s' como mascote (renomeie para ditto.png para fixar a escolha).",
            candidatos[0].name,
        )
        return candidatos[0]
    return None


def load_mascot_sprite(height: int) -> tuple[Path, QPixmap] | None:
    """O arquivo escolhido e a imagem pronta para exibir, ou None.

    O caminho vem junto porque quem desenha também precisa saber se a
    arte é um GIF animado, e procurá-la uma segunda vez no disco para
    descobrir isso seria trabalho repetido.

    `FastTransformation` é a interpolação por vizinho mais próximo, a
    única que preserva a borda dura do pixel art. A suavização que o Qt
    usa por padrão transformaria qualquer sprite em um borrão.
    """
    caminho = find_mascot_file()
    if caminho is None:
        logger.info(
            "Nenhuma imagem em assets/%s — a janela abre sem o mascote.", MASCOT_PATH[0]
        )
        return None

    pixmap = QPixmap(str(caminho))
    if pixmap.isNull():
        logger.warning("'%s' não pôde ser lido como imagem.", caminho)
        return None

    return caminho, pixmap.scaledToHeight(height, Qt.TransformationMode.FastTransformation)


# --- O widget -------------------------------------------------------------

# Quanto de folga o widget reserva acima e ao redor da figura, em fração
# da altura dela. Sem essa folga o pulo da comemoração e o esticão seriam
# cortados pela borda do widget.
_HEADROOM = 0.40
_SIDEROOM = 0.20

# Intervalo entre quadros. 33 ms são ~30 quadros por segundo, suficiente
# para um movimento macio e barato o bastante para não aparecer no uso de
# CPU de uma janela que fica aberta.
_FRAME_MS = 33


class MascotWidget(QWidget):
    """A figura do mascote, animada conforme o estado do aplicativo.

    Sem imagem na pasta de assets, o widget se esconde e não ocupa espaço
    — a janela continua inteira, só sem a figura.
    """

    def __init__(self, height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        arte = load_mascot_sprite(height)
        self._sprite = arte[1] if arte is not None else None
        self._movie: QMovie | None = None
        self._state = MascotState.IDLE
        self._base_state = MascotState.IDLE
        self._elapsed = 0.0
        self._animated = True

        if arte is None:
            self.hide()
            return

        self.setFixedSize(
            round(self._sprite.width() * (1 + 2 * _SIDEROOM)),
            round(self._sprite.height() * (1 + _HEADROOM)),
        )
        self._setup_movie(arte[0])

        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._advance)

    # --- Arte animada ----------------------------------------------------

    def _setup_movie(self, caminho: Path) -> None:
        """Prepara o GIF, se a arte da pasta for um GIF animado.

        Um GIF de um quadro só não ganha nada com isto e continua sendo
        tratado como imagem estática.
        """
        if caminho.suffix.lower() != ".gif":
            return

        movie = QMovie(str(caminho))
        if not movie.isValid() or movie.frameCount() <= 1:
            return

        movie.setScaledSize(self._sprite.size())
        movie.frameChanged.connect(lambda _frame: self.update())
        self._movie = movie
        logger.info("Mascote animado: reproduzindo '%s'.", caminho.name)

    # --- Estado -----------------------------------------------------------

    def set_state(self, state: MascotState) -> None:
        """Troca o que o mascote está fazendo.

        Uma reação (comemorar, levar um susto) roda até o fim e devolve o
        mascote ao último estado contínuo — quem chama não precisa se
        lembrar de desfazer nada.
        """
        if self._sprite is None:
            return
        if duration_of(state) is None:
            self._base_state = state
        self._state = state
        self._elapsed = 0.0
        self._sync_timer()
        self.update()

    def set_animated(self, animated: bool) -> None:
        """Liga ou desliga a animação (opção "Animações")."""
        self._animated = animated
        if self._sprite is None:
            return
        if not animated:
            # Parado significa parado na pose neutra: uma figura
            # congelada no meio de um pulo pareceria defeito.
            self._elapsed = 0.0
            self._state = self._base_state
        self._sync_timer()
        self.update()

    def current_state(self) -> MascotState:
        return self._state

    # --- Animação ---------------------------------------------------------

    def _sync_timer(self) -> None:
        """O temporizador só roda quando há motivo: animação ligada e
        widget visível. Uma janela minimizada não gasta CPU desenhando
        quadros que ninguém vê."""
        if self._sprite is None:
            return
        precisa = self._animated and self.isVisible()
        if precisa and not self._timer.isActive():
            self._timer.start()
        elif not precisa and self._timer.isActive():
            self._timer.stop()

        if self._movie is not None:
            if precisa and self._movie.state() != QMovie.MovieState.Running:
                self._movie.start()
            elif not precisa and self._movie.state() == QMovie.MovieState.Running:
                self._movie.setPaused(True)

    def _advance(self) -> None:
        self._elapsed += _FRAME_MS / 1000
        duration = duration_of(self._state)
        if duration is not None and self._elapsed >= duration:
            self._state = self._base_state
            self._elapsed = 0.0
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 — nome do Qt
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:  # noqa: N802 — nome do Qt
        super().hideEvent(event)
        self._sync_timer()

    # --- Desenho ----------------------------------------------------------

    def current_pose(self) -> Pose:
        if not self._animated:
            return NEUTRAL_POSE
        return pose_for(self._state, self._elapsed)

    def sprite_rect(self, pose: Pose) -> QRect:
        """Onde a figura é desenhada, dada a pose.

        Ancorada embaixo e no centro: é isso que faz o esmagamento
        parecer peso apoiado no chão, em vez de a figura inteira encolher
        no ar.
        """
        sprite = self._sprite
        largura = round(sprite.width() * pose.scale_x)
        altura = round(sprite.height() * pose.scale_y)
        base = self.height()
        x = round((self.width() - largura) / 2 + pose.offset_x * sprite.height())
        y = round(base - altura + pose.offset_y * sprite.height())
        return QRect(x, y, largura, altura)

    def paintEvent(self, event) -> None:  # noqa: N802 — nome do Qt
        if self._sprite is None:
            return
        fonte = self._movie.currentPixmap() if self._movie is not None else self._sprite
        if fonte.isNull():  # pragma: no cover — GIF ainda sem quadro pronto
            fonte = self._sprite

        painter = QPainter(self)
        # Vizinho mais próximo, como no carregamento: o pixel art tem que
        # continuar com a borda dura mesmo deformado.
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawPixmap(self.sprite_rect(self.current_pose()), fonte)
        painter.end()
