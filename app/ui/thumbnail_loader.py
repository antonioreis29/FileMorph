"""
As miniaturas das páginas, desenhadas em segundo plano.

A janela de organização não pode travar enquanto um PDF de centenas de
páginas é desenhado. O `ThumbnailLoader` abre o documento numa thread
própria e desenha só as páginas que a janela pede — as que estão na tela,
mais uma tela de folga acima e abaixo. Rolar troca a fila de pedidos: o que
saiu de vista deixa de ser desenhado.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from app.core.page_organizer import PageOrganizerError, PagePreview
from app.utils.file_utils import get_filename
from app.utils.logger import get_logger

logger = get_logger("ui.page_organizer")


class ThumbnailLoader(QThread):
    """Abre o documento e desenha miniaturas numa thread própria.

    O documento é aberto uma vez só, na própria thread, e usado apenas por
    ela — a biblioteca de PDF não é segura para uso simultâneo. A janela
    pede páginas com `request`, que *substitui* os pedidos pendentes em vez
    de somar: depois de rolar a tela, o que importa é o que está à vista
    agora.
    """

    opened = Signal(int)  # quantidade de páginas
    failed = Signal(str)  # mensagem pronta para o usuário
    rendered = Signal(int, QImage)  # página original, miniatura (nula se falhou)

    def __init__(
        self,
        path: str,
        open_preview: Callable[[str], PagePreview],
        pixel_side: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._path = path
        self._open_preview = open_preview
        self._pixel_side = max(1, pixel_side)
        self._condition = threading.Condition()
        self._pending: list[int] = []
        self._stopping = False

    def request(self, pages: list[int]) -> None:
        with self._condition:
            self._pending = list(pages)
            self._condition.notify()

    def stop(self) -> None:
        """Pede para parar e espera a thread terminar. A espera é curta: no
        pior caso, a miniatura que estiver sendo desenhada."""
        with self._condition:
            self._stopping = True
            self._pending = []
            self._condition.notify()
        self.wait()

    def run(self) -> None:
        try:
            preview = self._open_preview(self._path)
        except PageOrganizerError as exc:
            self.failed.emit(str(exc))
            return
        except Exception:  # noqa: BLE001 — a janela nunca deve receber um traceback
            logger.exception("Falha ao abrir %s para organizar as páginas", self._path)
            self.failed.emit(
                f"Não foi possível abrir '{get_filename(self._path)}'. Veja os logs "
                "para detalhes."
            )
            return

        try:
            with self._condition:
                if self._stopping:
                    return
            self.opened.emit(preview.page_count)
            while (page := self._next_page()) is not None:
                self.rendered.emit(page, self._render(preview, page))
        finally:
            preview.close()

    def _next_page(self) -> int | None:
        with self._condition:
            while not self._pending and not self._stopping:
                self._condition.wait()
            if self._stopping:
                return None
            return self._pending.pop(0)

    def _render(self, preview: PagePreview, page: int) -> QImage:
        try:
            thumbnail = preview.render_thumbnail(page, self._pixel_side)
            image = QImage(
                thumbnail.samples,
                thumbnail.width,
                thumbnail.height,
                3 * thumbnail.width,
                QImage.Format.Format_RGB888,
            )
            # A conversão cria uma cópia que é da própria imagem — a original
            # só aponta para os bytes da miniatura — e no formato mais rápido
            # de desenhar na tela.
            return image.convertToFormat(QImage.Format.Format_RGB32)
        except Exception:  # noqa: BLE001 — uma página ruim não derruba as outras
            logger.warning(
                "Miniatura da página %d de %s falhou", page + 1, self._path, exc_info=True
            )
            return QImage()

