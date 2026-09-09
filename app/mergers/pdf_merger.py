"""
Junção de arquivos em um único PDF (FASE 4 do briefing).

É o primeiro merger real do FileMorph. Aceita PDFs e imagens na mesma
seleção, na ordem em que aparecem na lista da interface (item 12):

    contrato.pdf + foto.jpg + anexo.pdf  ->  documento_final.pdf

Imagens não são páginas de PDF por si só, então cada uma passa antes
pelo `ImageToPdfConverter`, gerando um PDF temporário de uma página que
é concatenado com os demais. Esse é exatamente o "pipeline de conversão
intermediária" do item 13, e os arquivos intermediários ficam sob o
controle do `temp_manager` (item 24), que os apaga ao final — tenha a
junção dado certo ou errado.

Um único merger cobre PDF+PDF, imagens+imagens e a mistura dos dois. É
proposital: dois mergers aceitando os mesmos formatos deixariam o
registro de compatibilidade ambíguo, sem uma regra clara de qual dos
dois deveria atender o pedido.
"""

from __future__ import annotations

import time
from contextlib import ExitStack
from pathlib import Path

from app.converters.pdf_converter import ImageToPdfConverter
from app.core.merger import BaseMerger, MergeResult
from app.core.task_context import NULL_CONTEXT, OperationCancelled, TaskContext
from app.utils.file_utils import (
    ensure_directory,
    get_extension,
    get_filename,
    get_stem,
    temp_output_path,
)
from app.utils.logger import get_logger
from app.utils.temp_manager import temp_manager

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:  # pragma: no cover — depende do ambiente
    PdfReader = PdfWriter = None  # type: ignore[assignment]

PYPDF_AVAILABLE = PdfWriter is not None

logger = get_logger("mergers.pdf")


class _MergeInputError(Exception):
    """Problema em um arquivo de entrada, com a mensagem já pronta para o
    usuário. Serve para interromper a junção lá de dentro do laço sem
    espalhar checagens de retorno pelo caminho."""


# Formatos aceitos na entrada. As imagens entram pelo caminho da
# conversão intermediária descrita no cabeçalho.
IMAGE_FORMATS: set[str] = {"png", "jpg", "jpeg", "webp"}
ACCEPTED_FORMATS: set[str] = {"pdf"} | IMAGE_FORMATS


class PdfMerger(BaseMerger):
    """Concatena PDFs e imagens em um único PDF, preservando a ordem."""

    @property
    def accepted_formats(self) -> set[str]:
        return set(ACCEPTED_FORMATS)

    @property
    def output_format(self) -> str:
        return "pdf"

    def merge(
        self,
        input_paths: list[str],
        output_path: str,
        context: TaskContext | None = None,
    ) -> MergeResult:
        context = context or NULL_CONTEXT
        destination = Path(output_path)
        started_at = time.monotonic()

        if not PYPDF_AVAILABLE:  # rede de segurança: sem pypdf nem é registrado
            return self._failure(
                input_paths,
                "A junção de PDFs depende do pypdf, que não está instalado. "
                "Rode 'pip install -r requirements.txt' para habilitá-la.",
            )
        if not input_paths:
            return self._failure(input_paths, "Nenhum arquivo foi selecionado para juntar.")

        missing = [p for p in input_paths if not Path(p).is_file()]
        if missing:
            return self._failure(
                input_paths,
                f"Arquivo não encontrado: {get_filename(missing[0])}.",
            )

        session_id = temp_manager.new_session()
        temp_output: Path | None = None
        try:
            sources = self._as_pdf_sources(input_paths, session_id, context)

            ensure_directory(destination.parent)
            temp_output = temp_output_path(destination)
            self._write_merged_pdf(sources, temp_output, context)

            temp_output.replace(destination)
            temp_output = None

        except OperationCancelled:
            # Não é falha: o `finally` limpa o temporário e os
            # intermediários, e a fila trata o cancelamento.
            raise
        except _MergeInputError as exc:
            return self._failure(input_paths, str(exc))
        except PermissionError:
            return self._failure(
                input_paths,
                "Sem permissão para gravar o arquivo final. Escolha outra pasta.",
            )
        except OSError as exc:
            logger.exception("Erro de sistema ao juntar em %s", output_path)
            detail = getattr(exc, "strerror", None) or str(exc)
            return self._failure(input_paths, f"Não foi possível gravar o PDF final ({detail}).")
        except Exception as exc:  # noqa: BLE001 — a UI nunca deve receber um traceback
            logger.exception("Falha inesperada ao juntar arquivos em %s", output_path)
            return self._failure(
                input_paths,
                "Não foi possível juntar estes arquivos. Um deles pode estar "
                f"corrompido ou protegido por senha ({type(exc).__name__}).",
            )
        finally:
            if temp_output is not None:
                temp_output.unlink(missing_ok=True)
            # Os PDFs intermediários das imagens são descartados aqui,
            # com sucesso ou com falha (item 24).
            temp_manager.cleanup(session_id)

        logger.info(
            "Junção concluída | pypdf | %d arquivo(s) -> %s | %.2fs",
            len(input_paths),
            get_filename(destination),
            time.monotonic() - started_at,
        )
        return MergeResult(
            success=True, input_paths=input_paths, output_path=str(destination)
        )

    def _as_pdf_sources(
        self, input_paths: list[str], session_id: str, context: TaskContext
    ) -> list[Path]:
        """Lista de PDFs a concatenar, na ordem recebida, convertendo as
        imagens em PDFs temporários pelo caminho (item 13).

        A preparação das entradas conta como a primeira metade do
        trabalho; a concatenação em si é a segunda.
        """
        converter = ImageToPdfConverter()
        session_dir = temp_manager.session_dir(session_id)
        sources: list[Path] = []
        total = len(input_paths)

        for index, path in enumerate(input_paths):
            # Cada arquivo é um ponto seguro para parar.
            context.check_cancelled()
            context.report_step(index, total * 2)

            if get_extension(path) == "pdf":
                sources.append(Path(path))
                continue

            # O índice no nome evita colisão entre duas imagens de mesmo
            # nome vindas de pastas diferentes.
            temp_pdf = session_dir / f"{index:04d}_{get_stem(path)}.pdf"
            # O contexto vai sem progresso: o avanço da conversão de uma
            # imagem isolada não pode reescrever o avanço da junção.
            result = converter.convert(path, str(temp_pdf), context.cancellation_only())
            if not result.success:
                raise _MergeInputError(
                    result.error_message or f"Não foi possível usar '{get_filename(path)}'."
                )
            temp_manager.register(session_id, temp_pdf)
            sources.append(temp_pdf)

        return sources

    def _write_merged_pdf(
        self, sources: list[Path], temp_output: Path, context: TaskContext
    ) -> None:
        """Concatena os PDFs na ordem dada, gravando no arquivo temporário.

        Os arquivos de entrada ficam abertos até a gravação terminar
        porque o pypdf ainda lê deles enquanto escreve o resultado.
        """
        writer = PdfWriter()
        try:
            total = len(sources)
            with ExitStack() as open_files:
                for index, pdf_path in enumerate(sources):
                    context.check_cancelled()
                    context.report_step(total + index, total * 2)
                    handle = open_files.enter_context(open(pdf_path, "rb"))
                    reader = PdfReader(handle)
                    if reader.is_encrypted:
                        raise _MergeInputError(
                            f"'{get_filename(pdf_path)}' está protegido por senha. "
                            "Remova a proteção antes de juntar."
                        )
                    writer.append(reader)

                # A gravação final é indivisível: depois daqui não há
                # mais ponto seguro para interromper.
                context.check_cancelled()
                with open(temp_output, "wb") as output_file:
                    writer.write(output_file)
                context.report(100)
        finally:
            writer.close()

    def _failure(self, input_paths: list[str], message: str) -> MergeResult:
        logger.warning("Junção falhou | %d arquivo(s) | %s", len(input_paths), message)
        return MergeResult(success=False, input_paths=input_paths, error_message=message)
