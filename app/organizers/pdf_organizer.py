"""
Organização das páginas de um PDF (PyMuPDF).

Muda a ordem das páginas de um PDF e grava o resultado num arquivo novo:

    relatorio.pdf (1, 2, 3, 4)  ->  relatorio_reorganizado.pdf (3, 1, 4, 2)

**Por que o PyMuPDF.** É a biblioteca que o projeto já usa para
rasterizar páginas, e as miniaturas da janela de organização precisam
exatamente disso. E ela reordena do jeito certo: `Document.select`
rearranja a árvore de páginas do documento sem tocar no conteúdo delas —
texto, desenhos vetoriais e imagens continuam sendo os mesmos objetos —,
e ainda leva junto os marcadores e os links internos, que passam a
apontar para a página na posição nova. Copiar página por página para um
documento novo perderia os dois.

**A ordem é conferida duas vezes.** `select` aceita calado uma lista que
repete ou omite páginas, porque é assim que ele também serve para extrair
trechos. Então a ordem passa por `check_page_order` antes, e o arquivo
gravado é reaberto e contado depois, antes de ocupar o nome definitivo.

**A qualidade é a original.** Nada é rasterizado nem recomprimido com
perda: uma foto em JPEG sai byte a byte igual. A gravação compacta a
estrutura do arquivo (`_SAVE_OPTIONS`) — sem isso, um PDF moderno, que
guarda seus objetos comprimidos, sairia com quase o dobro do tamanho —, e
nessa compactação um stream que estava gravado *sem* compressão nenhuma
ganha compressão Flate, que é sem perda: os pixels continuam idênticos.

**PDF protegido fica de fora.** O que exige senha para abrir não tem como
ser lido. O que abre sem senha mas carrega uma senha de proprietário tem
restrições de edição do autor, e gravá-lo reorganizado jogaria essas
restrições fora sem ninguém perceber — a mesma regra que a junção de PDFs
já segue.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from app.core.page_organizer import (
    BasePageOrganizer,
    PageOrderResult,
    PageOrganizerError,
    PagePreview,
    PageThumbnail,
    check_page_order,
)
from app.core.task_context import NULL_CONTEXT, OperationCancelled, TaskContext
from app.utils.file_utils import (
    ensure_directory,
    get_extension,
    get_filename,
    refers_to_same_path,
    temp_output_path,
)
from app.utils.logger import get_logger

try:  # PyMuPDF >= 1.24 expõe o nome novo; versões antigas, só o antigo.
    import pymupdf
except ImportError:  # pragma: no cover — depende da versão instalada
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None  # type: ignore[assignment]

PYMUPDF_AVAILABLE = pymupdf is not None

logger = get_logger("organizers.pdf")

# Opções de gravação do PDF reorganizado: descarta os objetos que ficaram
# sem uso na reorganização (a árvore de páginas antiga), agrupa os objetos
# em streams de objetos e comprime o que estava sem compressão — tudo sem
# perda. Ver "A qualidade é a original" no cabeçalho.
_SAVE_OPTIONS: dict[str, int | bool] = {"garbage": 1, "deflate": True, "use_objstms": 1}


def _unavailable_message() -> str:
    return (
        "Organizar as páginas de um PDF depende do PyMuPDF, que não está "
        "instalado. Rode 'pip install -r requirements.txt' para habilitar."
    )


def _open_pdf(path: Path):
    """Abre o PDF para organizar, ou explica por que não dá."""
    name = get_filename(path)
    if not path.is_file():
        raise PageOrganizerError(f"O arquivo '{name}' não foi encontrado.")

    try:
        document = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001 — PyMuPDF sinaliza arquivo ruim assim
        logger.warning("PDF ilegível: %s (%s)", path, exc)
        raise PageOrganizerError(
            f"'{name}' não é um PDF válido ou está corrompido."
        ) from exc

    try:
        if not document.is_pdf:
            raise PageOrganizerError(f"'{name}' não é um PDF válido ou está corrompido.")
        if document.needs_pass:
            raise PageOrganizerError(
                f"'{name}' está protegido por senha. Remova a proteção antes de "
                "organizar as páginas."
            )
        if (document.metadata or {}).get("encryption"):
            raise PageOrganizerError(
                f"'{name}' tem proteção contra alterações definida pelo autor. "
                "Remova a proteção antes de organizar as páginas."
            )
        if document.page_count == 0:
            raise PageOrganizerError(f"'{name}' não tem páginas.")
    except BaseException:
        document.close()
        raise
    return document


def _save(document, path: Path) -> None:
    try:
        document.save(str(path), **_SAVE_OPTIONS)
    except TypeError:
        # PyMuPDF anterior à 1.24 não conhece `use_objstms`. Sem ela o
        # arquivo sai maior, mas com o mesmo conteúdo.
        options = {key: value for key, value in _SAVE_OPTIONS.items() if key != "use_objstms"}
        document.save(str(path), **options)


class _PdfPreview(PagePreview):
    """Um PDF aberto para a janela de organização desenhar as miniaturas."""

    def __init__(self, document) -> None:
        self._document = document

    @property
    def page_count(self) -> int:
        return self._document.page_count

    def render_thumbnail(self, page_index: int, max_side: int) -> PageThumbnail:
        page = self._document[page_index]
        longest = max(page.rect.width, page.rect.height, 1.0)
        zoom = max(1, max_side) / longest
        # Sem canal alfa: a página é opaca, e a miniatura fica com 3 bytes
        # por pixel, que é o formato prometido por `PageThumbnail`.
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return PageThumbnail(pixmap.width, pixmap.height, bytes(pixmap.samples))

    def close(self) -> None:
        self._document.close()


class PdfPageOrganizer(BasePageOrganizer):
    """Reordena as páginas de um PDF num arquivo novo (PyMuPDF)."""

    @property
    def accepted_formats(self) -> set[str]:
        return {"pdf"}

    def open_preview(self, path: str) -> PagePreview:
        if not PYMUPDF_AVAILABLE:  # rede de segurança: sem PyMuPDF nem é registrado
            raise PageOrganizerError(_unavailable_message())
        return _PdfPreview(_open_pdf(Path(path)))

    def reorder(
        self,
        input_path: str,
        output_path: str,
        page_order: Sequence[int],
        context: TaskContext | None = None,
    ) -> PageOrderResult:
        context = context or NULL_CONTEXT
        source = Path(input_path)
        destination = Path(output_path)
        order = list(page_order)
        started_at = time.monotonic()

        if not PYMUPDF_AVAILABLE:  # rede de segurança: sem PyMuPDF nem é registrado
            return self._failure(input_path, _unavailable_message())
        if get_extension(destination) != "pdf":
            return self._failure(
                input_path, "O arquivo com a nova ordem precisa ser salvo como .pdf."
            )
        if refers_to_same_path(source, destination):
            return self._failure(
                input_path,
                "Escolha outro nome para o arquivo reorganizado: o FileMorph "
                "nunca altera o arquivo original.",
            )

        document = None
        temp_output: Path | None = None
        try:
            context.check_cancelled()
            document = _open_pdf(source)
            page_count = document.page_count
            check_page_order(order, page_count)
            context.report(10)

            # Último ponto seguro antes de escrever qualquer coisa em disco.
            context.check_cancelled()
            document.select(order)
            ensure_directory(destination.parent)
            temp_output = temp_output_path(destination)
            _save(document, temp_output)
            document.close()
            document = None
            context.report(80)

            self._verify(temp_output, page_count)
            # Depois de gravado, ainda dá para desistir: o temporário é
            # descartado e um arquivo que já ocupasse o destino fica intacto.
            context.check_cancelled()
            temp_output.replace(destination)
            temp_output = None

        except OperationCancelled:
            raise  # não é falha: quem trata é a fila
        except PageOrganizerError as exc:
            return self._failure(input_path, str(exc))
        except PermissionError:
            return self._failure(
                input_path,
                "Sem permissão para gravar o arquivo reorganizado. Escolha outra pasta.",
            )
        except OSError as exc:
            logger.exception("Erro de sistema ao reorganizar %s", input_path)
            detail = getattr(exc, "strerror", None) or str(exc)
            return self._failure(
                input_path, f"Não foi possível gravar o PDF reorganizado ({detail})."
            )
        except Exception:  # noqa: BLE001 — a UI nunca deve receber um traceback
            logger.exception("Falha inesperada ao reorganizar %s", input_path)
            return self._failure(
                input_path,
                "Erro inesperado ao reorganizar este PDF. Veja os logs para detalhes.",
            )
        finally:
            if document is not None:
                document.close()
            if temp_output is not None:
                temp_output.unlink(missing_ok=True)

        context.report(100)
        logger.info(
            "Páginas reorganizadas | PyMuPDF | %s -> %s | %d página(s) | %.2fs",
            get_filename(source),
            get_filename(destination),
            len(order),
            time.monotonic() - started_at,
        )
        return PageOrderResult(
            success=True, input_path=input_path, output_path=str(destination)
        )

    @staticmethod
    def _verify(written: Path, expected_pages: int) -> None:
        """Reabre o arquivo gravado e confere que nenhuma página se perdeu."""
        try:
            with pymupdf.open(written) as check:
                found = check.page_count
        except Exception as exc:  # noqa: BLE001 — PyMuPDF sinaliza arquivo ruim assim
            raise PageOrganizerError(
                "O PDF reorganizado não pôde ser conferido depois de gravado. "
                "Nada foi salvo."
            ) from exc
        if found != expected_pages:
            raise PageOrganizerError(
                f"O PDF reorganizado saiu com {found} página(s) em vez de "
                f"{expected_pages}. Nada foi salvo."
            )

    @staticmethod
    def _failure(input_path: str, message: str) -> PageOrderResult:
        logger.warning("Reorganização falhou | %s | %s", get_filename(input_path), message)
        return PageOrderResult(success=False, input_path=input_path, error_message=message)
