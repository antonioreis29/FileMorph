"""
A grade de páginas da janela de organização: a aparência de cada card e o
arrastar e soltar.

## Por que um QListView, e não um widget por página

A lista de arquivos da janela principal usa um QFrame por arquivo, e com
dez arquivos isso é o certo. Um PDF pode ter mil páginas: mil cards com
rótulos e imagens deixariam a janela lenta para abrir e para
redimensionar. O QListView desenha só o que está na tela, e cada card é
pintado pelo `PageCardDelegate` com as cores da paleta do tema — a mesma
família visual dos cards de arquivo.

## Arrastar e soltar sem o comportamento padrão do Qt

O arrastar interno do QListView tem duas armadilhas. No modo ícone, ele
move o card para uma posição livre na tela em vez de mudar a ordem. E,
depois de um "mover", ele mesmo apaga as linhas de origem se achar que
ninguém cuidou delas — exatamente o tipo de coisa que poderia sumir com
uma página. Por isso o arrastar é feito à mão em `PageGridView`: o ponto
de soltura vira uma posição de inserção, e quem muda a ordem é o modelo
(`PageOrderModel.move_rows`), a pedido da janela.
"""

from __future__ import annotations

from uuid import uuid4

from PySide6.QtCore import (
    QByteArray,
    QMimeData,
    QModelIndex,
    QPoint,
    QRect,
    QRectF,
    QSize,
    QSizeF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QDrag, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOption,
    QStyleOptionViewItem,
)

from app.ui.page_order_model import PAGE_ROLE, THUMBNAIL_FAILED_ROLE, THUMBNAIL_ROLE
from app.ui.styles import Palette

# Célula da grade, em pixels lógicos. O card é pintado centrado dentro
# dela, e a sobra ao redor faz o espaço entre os cards. A célula inteira é
# o item, e não só o card, para que não haja vão entre um item e outro:
# soltar uma página no espaço entre dois cards precisa cair em algum deles.
#
# Este é o tamanho mínimo. A largura real cresce para dividir a largura da
# grade igualmente entre as colunas (ver `PageGridView._fit_cells_to_width`),
# em vez de deixar uma faixa vazia do lado direito.
CELL_SIZE = QSize(158, 200)
_CARD_SIZE = QSize(146, 188)
_CARD_MARGIN = (CELL_SIZE.height() - _CARD_SIZE.height()) // 2
_CARD_PADDING = 9

# Área da miniatura dentro do card. Uma página em retrato ocupa a altura
# inteira; uma em paisagem, a largura.
_THUMBNAIL_AREA = QSize(128, 144)
THUMBNAIL_SIDE = 144

# Formato do arrastar interno: `<marca da grade>:<posições separadas por
# vírgula>`. É um tipo próprio para que nada vindo de fora (um arquivo
# arrastado do Explorer, por exemplo) seja confundido com páginas, e a
# marca é única por grade para que páginas arrastadas de *outra* janela do
# FileMorph — outro documento, talvez outro processo — não sejam aceitas
# como se fossem posições deste.
_PAGE_POSITIONS_MIME = "application/x-filemorph-page-positions"

# Rolagem automática ao arrastar perto da borda de cima ou de baixo.
_AUTOSCROLL_MARGIN = 40
_AUTOSCROLL_STEP = 22


def _fit(size: QSizeF, area: QRectF) -> QRectF:
    """O maior retângulo com a proporção de `size` que cabe centrado em `area`."""
    if size.width() <= 0 or size.height() <= 0:
        return QRectF(area)
    scale = min(area.width() / size.width(), area.height() / size.height())
    width, height = size.width() * scale, size.height() * scale
    return QRectF(
        area.center().x() - width / 2, area.center().y() - height / 2, width, height
    )


# --- Aparência de cada card ----------------------------------------------------


class PageCardDelegate(QStyledItemDelegate):
    """Pinta cada página como um card.

    O QSS não alcança o que um delegate desenha, então as cores vêm direto
    da `Palette` do tema — a mesma fonte de cor de `styles.py`, o que
    mantém os cards de página coerentes com os cards de arquivo nos dois
    temas.

    O número em destaque, no canto da miniatura, é a posição no arquivo
    novo, e muda enquanto o usuário reorganiza. A legenda é a página no
    original, que acompanha o card; ela ganha a cor de destaque quando a
    página saiu do lugar, para que dê para ver de relance o que mudou.
    """

    def __init__(self, palette: Palette, parent=None) -> None:
        super().__init__(parent)
        self._palette = palette

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802 — nome do Qt
        view = self.parent()
        if isinstance(view, PageGridView):
            return view.cell_size()
        return QSize(CELL_SIZE)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        page = index.data(PAGE_ROLE)
        if page is None:
            return
        palette = self._palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        cell = QRectF(option.rect)
        card = QRectF(
            cell.center().x() - _CARD_SIZE.width() / 2,
            cell.center().y() - _CARD_SIZE.height() / 2,
            _CARD_SIZE.width(),
            _CARD_SIZE.height(),
        )
        if selected:
            fill, border = palette.accent_soft, QPen(QColor(palette.accent), 2)
        else:
            fill = palette.surface_alt if hovered else palette.surface
            border = QPen(QColor(palette.border), 1)
        painter.setPen(border)
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), 14, 14)

        area = QRectF(
            card.left() + _CARD_PADDING,
            card.top() + _CARD_PADDING,
            _THUMBNAIL_AREA.width(),
            _THUMBNAIL_AREA.height(),
        )
        self._paint_page(painter, area, index)
        self._paint_position(painter, area, index.row() + 1, option)

        caption = QRectF(card.left() + 4, area.bottom() + 2, card.width() - 8, card.bottom() - area.bottom() - 4)
        moved = page != index.row()
        font = QFont(option.font)
        font.setPixelSize(12)
        font.setBold(moved)
        painter.setFont(font)
        painter.setPen(QColor(palette.accent if moved else palette.text_secondary))
        painter.drawText(caption, Qt.AlignmentFlag.AlignCenter, f"Página {page + 1}")
        painter.restore()

    def _paint_page(self, painter: QPainter, area: QRectF, index: QModelIndex) -> None:
        palette = self._palette
        image = index.data(THUMBNAIL_ROLE)
        if isinstance(image, QImage) and not image.isNull():
            outline = _fit(image.deviceIndependentSize(), area)
            painter.drawImage(outline, image)
        else:
            # Sem miniatura ainda: a silhueta de uma folha A4, para a grade
            # não parecer vazia enquanto as páginas vão sendo desenhadas.
            outline = _fit(QSizeF(210, 297), area)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(palette.surface_alt))
            painter.drawRect(outline)
            failed = bool(index.data(THUMBNAIL_FAILED_ROLE))
            painter.setPen(QColor(palette.text_secondary))
            painter.drawText(
                outline, Qt.AlignmentFlag.AlignCenter, "sem prévia" if failed else "…"
            )
        painter.setPen(QPen(QColor(palette.border), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(outline)

    def _paint_position(
        self, painter: QPainter, area: QRectF, number: int, option: QStyleOptionViewItem
    ) -> None:
        font = QFont(option.font)
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        text = str(number)
        width = max(22, painter.fontMetrics().horizontalAdvance(text) + 14)
        badge = QRectF(area.left() + 3, area.top() + 3, width, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._palette.accent))
        painter.drawRoundedRect(badge, 10, 10)
        painter.setPen(QColor(self._palette.on_accent))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)



# --- Grade com arrastar e soltar -------------------------------------------------


class PageGridView(QListView):
    """A grade de cards, com o arrastar e soltar feito à mão.

    Ver "Arrastar e soltar sem o comportamento padrão do Qt" no topo do
    módulo. Esta classe só traduz gestos em pedidos — `pages_dropped` e
    `move_requested` —; quem muda a ordem é o modelo, a pedido da janela.
    """

    pages_dropped = Signal(list, int)  # posições arrastadas, posição de inserção
    move_requested = Signal(str)  # "start" | "back" | "forward" | "end"
    viewport_resized = Signal()

    # Atalhos para mover a seleção sem o mouse, com Ctrl pressionado. As
    # chaves são inteiros porque é assim que `QKeyEvent.key()` as entrega.
    _KEYBOARD_MOVES = {
        int(Qt.Key.Key_Home): "start",
        int(Qt.Key.Key_Left): "back",
        int(Qt.Key.Key_Right): "forward",
        int(Qt.Key.Key_End): "end",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("pageGrid")
        # Modo lista com fluxo da esquerda para a direita e quebra de linha:
        # a aparência de grade, com a semântica de uma lista ordenada.
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(False)

        self._cell = QSize(CELL_SIZE)
        self._drag_token = uuid4().hex
        self._accent = QColor(Qt.GlobalColor.black)
        self._on_accent = QColor(Qt.GlobalColor.white)
        # Onde desenhar a marca de soltura: (linha do card de referência,
        # marca à direita dele?). None quando não há arrastar em curso.
        self._drop_marker: tuple[int, bool] | None = None
        self._last_drag_position = QPoint()
        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(30)
        self._autoscroll.timeout.connect(self._autoscroll_step)

    def set_palette_colors(self, palette: Palette) -> None:
        """Cores do que a grade pinta por conta própria: a marca de soltura
        e a contagem no card arrastado."""
        self._accent = QColor(palette.accent)
        self._on_accent = QColor(palette.on_accent)

    def selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.selectionModel().selectedIndexes()})

    # --- Geometria -----------------------------------------------------------

    def cell_size(self) -> QSize:
        return QSize(self._cell)

    def _layout_width(self) -> int:
        """A largura em que o QListView distribui os itens de cada linha.

        É a mesma conta que o próprio Qt faz ao diagramar uma lista com
        fluxo da esquerda para a direita (`QListViewPrivate::
        prepareItemsLayout`): a largura sem barra de rolagem, menos a
        largura da barra — sempre, mesmo quando ela não aparece. O Qt faz
        assim para a barra não piscar: descontá-la só quando aparece criaria
        um ciclo (menos colunas, mais linhas, barra aparece, menos colunas).
        Repetir a conta dele é o que garante que as colunas calculadas aqui
        são as mesmas que ele vai desenhar.
        """
        style = self.style()
        bar = self.verticalScrollBar()
        reserved = 0
        if not style.pixelMetric(QStyle.PixelMetric.PM_ScrollView_ScrollBarOverlap, None, bar):
            reserved = style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, bar)
            if style.styleHint(QStyle.StyleHint.SH_ScrollView_FrameOnlyAroundContents, None, self):
                option = QStyleOption()
                option.initFrom(self)
                reserved += 2 * style.pixelMetric(
                    QStyle.PixelMetric.PM_DefaultFrameWidth, option, self
                )
        return self.maximumViewportSize().width() - reserved

    def _fit_cells_to_width(self) -> None:
        """Divide a largura da grade igualmente entre as colunas, em vez de
        deixar uma faixa vazia do lado direito.

        Um pixel fica de fora da divisão porque o Qt só mantém um item na
        linha se ele terminar *antes* do limite: colunas que somassem
        exatamente a largura empurrariam a última para a linha de baixo.
        """
        available = self._layout_width() - 1
        columns = max(1, available // CELL_SIZE.width())
        cell = QSize(max(CELL_SIZE.width(), available // columns), CELL_SIZE.height())
        if cell != self._cell:
            self._cell = cell
            self.scheduleDelayedItemsLayout()

    def reset(self) -> None:
        super().reset()
        self._fit_cells_to_width()

    def insertion_row_at(self, position: QPoint) -> int:
        """A posição de inserção para uma soltura em `position` (viewport).

        Sobre a metade esquerda de um card, as páginas entram antes dele; na
        metade direita, depois. À direita do último card de uma linha, entram
        depois dele; abaixo da última linha, no fim do documento.
        """
        count = self.model().rowCount() if self.model() is not None else 0
        if count == 0:
            return 0
        index = self.indexAt(position)
        if index.isValid():
            rect = self.visualRect(index)
            return index.row() + (1 if position.x() >= rect.center().x() else 0)
        line_start = self.indexAt(QPoint(1, position.y()))
        if not line_start.isValid():
            return count
        return self._last_row_in_line(line_start.row()) + 1

    def rows_near_viewport(self) -> list[int]:
        """As linhas cujas miniaturas vale desenhar agora, na ordem em que
        vale desenhá-las: as visíveis, depois uma tela abaixo, depois uma
        tela acima (da mais próxima para a mais distante)."""
        count = self.model().rowCount() if self.model() is not None else 0
        if count == 0:
            return []
        area = self.viewport().rect()
        top = self.indexAt(QPoint(1, 1))
        if not top.isValid():
            # A grade ainda não foi diagramada: sem geometria, vale o começo
            # do documento — e não o documento inteiro.
            return list(range(min(count, 60)))
        first = top.row()
        bottom = self.indexAt(QPoint(1, max(1, area.height() - 1)))
        last = self._last_row_in_line(bottom.row()) if bottom.isValid() else count - 1
        last = max(first, last)
        span = last - first + 1
        visible = list(range(first, last + 1))
        below = list(range(last + 1, min(count, last + 1 + span)))
        above = list(range(first - 1, max(-1, first - 1 - span), -1))
        return visible + below + above

    def _last_row_in_line(self, row: int) -> int:
        model = self.model()
        top = self.visualRect(model.index(row, 0)).top()
        count = model.rowCount()
        while row + 1 < count and self.visualRect(model.index(row + 1, 0)).top() == top:
            row += 1
        return row

    def resizeEvent(self, event) -> None:  # noqa: N802 — nome do Qt
        super().resizeEvent(event)
        self._fit_cells_to_width()
        self.viewport_resized.emit()

    # --- Teclado -------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 — nome do Qt
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            action = self._KEYBOARD_MOVES.get(event.key())
            if action is not None:
                self.move_requested.emit(action)
                event.accept()
                return
        super().keyPressEvent(event)

    # --- Arrastar e soltar ------------------------------------------------------

    def startDrag(self, _supported_actions) -> None:  # noqa: N802 — nome do Qt
        rows = self.selected_rows()
        if not rows:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mime_for_rows(rows))
        drag.setPixmap(self._drag_pixmap(rows))
        drag.setHotSpot(QPoint(CELL_SIZE.width() // 2, CELL_SIZE.height() // 3))
        # O resultado do `exec` é ignorado de propósito: quem muda a ordem é
        # o `dropEvent`, e nada aqui remove linhas depois de um "mover".
        drag.exec(Qt.DropAction.MoveAction)
        self._end_drag_feedback()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 — nome do Qt
        if self.rows_from_mime(event.mimeData()) is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self._autoscroll.start()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 — nome do Qt
        if self.rows_from_mime(event.mimeData()) is None:
            event.ignore()
            return
        self._last_drag_position = event.position().toPoint()
        self._update_drop_marker()
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 — nome do Qt
        self._end_drag_feedback()
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802 — nome do Qt
        rows = self.rows_from_mime(event.mimeData())
        if rows is None:
            event.ignore()
            return
        destination = self.insertion_row_at(event.position().toPoint())
        self._end_drag_feedback()
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        if rows:
            self.pages_dropped.emit(rows, destination)

    def paintEvent(self, event) -> None:  # noqa: N802 — nome do Qt
        super().paintEvent(event)
        if self._drop_marker is None or self.model() is None:
            return
        row, after = self._drop_marker
        rect = self.visualRect(self.model().index(row, 0))
        if not rect.isValid():
            return
        x = rect.right() + 1 if after else rect.left()
        bar = QRectF(x - 2, rect.top() + _CARD_MARGIN, 4, _CARD_SIZE.height())
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._accent)
        painter.drawRoundedRect(bar, 2, 2)
        painter.end()

    def mime_for_rows(self, rows: list[int]) -> QMimeData:
        """O conteúdo de um arrastar que sai desta grade."""
        mime = QMimeData()
        payload = f"{self._drag_token}:{','.join(str(row) for row in rows)}"
        mime.setData(_PAGE_POSITIONS_MIME, QByteArray(payload.encode("ascii")))
        return mime

    def rows_from_mime(self, mime: QMimeData | None) -> list[int] | None:
        """As posições arrastadas, se o arrastar saiu desta grade; senão None.

        A marca é conferida em vez de `QDropEvent.source()`, que só existe
        para arrastos do mesmo processo: comparar marcas recusa do mesmo
        jeito páginas de outra janela, venham de onde vierem."""
        if mime is None or not mime.hasFormat(_PAGE_POSITIONS_MIME):
            return None
        raw = bytes(mime.data(_PAGE_POSITIONS_MIME)).decode("ascii", "ignore")
        token, separator, positions = raw.partition(":")
        if not separator or token != self._drag_token:
            return None
        return [int(part) for part in positions.split(",") if part.strip().isdigit()]

    def _marker_for(self, position: QPoint) -> tuple[int, bool] | None:
        count = self.model().rowCount() if self.model() is not None else 0
        if count == 0:
            return None
        insertion = self.insertion_row_at(position)
        index = self.indexAt(position)
        # A marca fica à esquerda do card que vai ser empurrado — exceto
        # quando o cursor está na metade direita de um card ou depois do fim
        # de uma linha: aí ela fica à direita do card anterior, na linha em
        # que o cursor está, e não no começo da linha de baixo.
        if index.isValid() and insertion == index.row():
            return index.row(), False
        return insertion - 1, True

    def _update_drop_marker(self) -> None:
        marker = self._marker_for(self._last_drag_position)
        if marker != self._drop_marker:
            self._drop_marker = marker
            self.viewport().update()

    def _end_drag_feedback(self) -> None:
        self._autoscroll.stop()
        if self._drop_marker is not None:
            self._drop_marker = None
            self.viewport().update()

    def _autoscroll_step(self) -> None:
        y = self._last_drag_position.y()
        bar = self.verticalScrollBar()
        if y < _AUTOSCROLL_MARGIN:
            delta = -_AUTOSCROLL_STEP
        elif y > self.viewport().height() - _AUTOSCROLL_MARGIN:
            delta = _AUTOSCROLL_STEP
        else:
            return
        before = bar.value()
        bar.setValue(before + delta)
        if bar.value() != before:
            self._update_drop_marker()

    def _drag_pixmap(self, rows: list[int]) -> QPixmap:
        """O card da primeira página arrastada, com a contagem quando são várias."""
        ratio = self.devicePixelRatio()
        pixmap = QPixmap(round(CELL_SIZE.width() * ratio), round(CELL_SIZE.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setOpacity(0.92)
        option = QStyleOptionViewItem()
        # O tamanho mínimo, e não o da célula atual: o card tem tamanho
        # fixo, e a sobra da célula só seria área transparente no arrastar.
        option.rect = QRect(QPoint(0, 0), CELL_SIZE)
        option.font = self.font()
        option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Selected
        self.itemDelegate().paint(painter, option, self.model().index(rows[0], 0))
        if len(rows) > 1:
            painter.setOpacity(1.0)
            font = QFont(self.font())
            font.setPixelSize(12)
            font.setBold(True)
            painter.setFont(font)
            badge = QRectF(CELL_SIZE.width() - 52, 2, 46, 22)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._accent)
            painter.drawRoundedRect(badge, 11, 11)
            painter.setPen(self._on_accent)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, f"+{len(rows) - 1}")
        painter.end()
        return pixmap

