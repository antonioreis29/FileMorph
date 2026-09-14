"""
A ordem das páginas na janela de organização, e as miniaturas já desenhadas.

Cada linha do modelo é uma posição no arquivo novo, e o valor dela é a
página original (0 = primeira) que ocupa essa posição. Toda mudança de
ordem passa por `move_pages`, a regra do núcleo que só produz permutações —
nenhuma página entra duas vezes nem some, qualquer que seja o arrastar.

## Miniaturas sob demanda

Desenhar todas as páginas logo de cara faria um PDF grande demorar a
mostrar qualquer coisa e ocupar memória à toa. As miniaturas guardadas aqui
têm um teto (`THUMBNAIL_CACHE_LIMIT`); as mais antigas saem da memória e são
refeitas se voltarem à tela.
"""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QImage

from app.core.page_organizer import is_original_order, move_pages

# Quantas miniaturas ficam guardadas na memória. Com folga para três telas
# cheias de cards num monitor grande, que é o máximo que se pede de uma
# vez (ver `PageGridView.rows_near_viewport`).
THUMBNAIL_CACHE_LIMIT = 240

PAGE_ROLE = int(Qt.ItemDataRole.UserRole) + 1
THUMBNAIL_ROLE = int(Qt.ItemDataRole.UserRole) + 2
THUMBNAIL_FAILED_ROLE = int(Qt.ItemDataRole.UserRole) + 3


class PageOrderModel(QAbstractListModel):
    """A ordem das páginas e as miniaturas já desenhadas.

    Cada linha é uma posição no arquivo novo, e o valor dela é a página
    original (0 = primeira) que ocupa essa posição. Toda mudança de ordem
    passa por `move_pages`, do core, e é aplicada como uma mudança de
    layout com os índices persistentes remapeados — é o que faz a seleção
    acompanhar as páginas movidas, em vez de ficar parada nas posições.
    """

    order_changed = Signal()

    def __init__(self, parent=None, thumbnail_limit: int = THUMBNAIL_CACHE_LIMIT) -> None:
        super().__init__(parent)
        self._order: list[int] = []
        # As miniaturas são guardadas pela página original, e não pela
        # posição: mudar a ordem não invalida nenhuma delas.
        self._thumbnails: OrderedDict[int, QImage] = OrderedDict()
        self._failed: set[int] = set()
        self._thumbnail_limit = max(1, thumbnail_limit)

    def set_page_count(self, page_count: int) -> None:
        self.beginResetModel()
        self._order = list(range(page_count))
        self._thumbnails.clear()
        self._failed.clear()
        self.endResetModel()
        self.order_changed.emit()

    # --- Leitura -----------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 — nome do Qt
        return 0 if parent.isValid() else len(self._order)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._order):
            return None
        page = self._order[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f"Página {page + 1}"
        if role in (Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.AccessibleTextRole):
            if page == index.row():
                return f"Página {page + 1} — na posição original"
            return f"Página {page + 1} do original, agora na posição {index.row() + 1}"
        if role == PAGE_ROLE:
            return page
        if role == THUMBNAIL_ROLE:
            return self._thumbnails.get(page)
        if role == THUMBNAIL_FAILED_ROLE:
            return page in self._failed
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
        )

    def page_order(self) -> list[int]:
        return list(self._order)

    def is_original_order(self) -> bool:
        return is_original_order(self._order)

    def needs_thumbnail(self, page: int) -> bool:
        return page not in self._thumbnails and page not in self._failed

    # --- Mudança de ordem -----------------------------------------------------

    def move_rows(self, positions: list[int], destination: int) -> int:
        """Aplica um arrastar e soltar (ver `move_pages` no core).

        Devolve a posição em que o bloco movido começa."""
        new_order, start = move_pages(self._order, positions, destination)
        self._apply_order(new_order)
        return start

    def restore_original_order(self) -> None:
        self._apply_order(list(range(len(self._order))))

    def _apply_order(self, new_order: list[int]) -> None:
        if new_order == self._order:
            return
        self.layoutAboutToBeChanged.emit()
        position_of = {page: row for row, page in enumerate(new_order)}
        old_indexes = self.persistentIndexList()
        new_indexes = [
            self.index(position_of[self._order[index.row()]], 0) for index in old_indexes
        ]
        self._order = new_order
        self.changePersistentIndexList(old_indexes, new_indexes)
        self.layoutChanged.emit()
        self.order_changed.emit()

    # --- Miniaturas ------------------------------------------------------------

    def set_thumbnail(self, page: int, image: QImage) -> None:
        """Guarda a miniatura de uma página. Uma imagem nula marca a página
        como sem prévia — ela continua no documento, só não tem desenho."""
        if not 0 <= page < len(self._order):
            return
        if image.isNull():
            self._failed.add(page)
        else:
            self._thumbnails[page] = image
            self._thumbnails.move_to_end(page)
            while len(self._thumbnails) > self._thumbnail_limit:
                evicted, _image = self._thumbnails.popitem(last=False)
                self._emit_page_changed(evicted)
        self._emit_page_changed(page)

    def _emit_page_changed(self, page: int) -> None:
        index = self.index(self._order.index(page), 0)
        self.dataChanged.emit(index, index, [THUMBNAIL_ROLE, THUMBNAIL_FAILED_ROLE])

