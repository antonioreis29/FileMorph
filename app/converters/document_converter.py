"""
Conversores de documentos (FASE 7 do briefing).

Cinco caminhos, cada um em sua classe, porque cada um depende de uma
coisa diferente e precisa poder ser oferecido (ou não) por conta própria:

- `DocxToTextConverter`  — DOCX → TXT, com python-docx.
- `TextToDocxConverter`  — TXT → DOCX, com python-docx.
- `TextToPdfConverter`   — TXT → PDF, com PyMuPDF.
- `PdfToTextConverter`   — PDF → TXT, com PyMuPDF.
- `DocxToPdfConverter`   — DOCX → PDF, com LibreOffice headless.

Só o último depende de um programa externo, e é o único que some do
seletor de formato numa máquina sem LibreOffice (ver
`app/utils/libreoffice_manager.py` para o porquê de não tentarmos
paginar um DOCX em Python).

**O que se perde em cada direção, e por quê.** Diferente de imagem ou
áudio, aqui a conversão quase nunca é simétrica, e isso é da natureza
dos formatos, não uma limitação do FileMorph:

- Ir para TXT guarda o texto e descarta tudo o que não é texto —
  negrito, cores, imagens, cabeçalho, numeração. Um arquivo .txt não
  tem onde guardar nada disso.
- Vir de TXT produz um documento de formatação neutra: uma fonte só, um
  parágrafo por linha. Não há como adivinhar uma intenção de layout que
  o arquivo de origem não registrou.
- DOCX → PDF preserva o layout, porque quem faz a paginação é um
  processador de texto de verdade.

A gravação é atômica nos cinco casos: o conteúdo vai para um arquivo
temporário ao lado do destino e só então é movido para o nome
definitivo. Uma falha no meio nunca deixa arquivo truncado nem destrói
um arquivo bom que já ocupasse aquele nome (item 18).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from app.core.converter import BaseConverter, ConversionResult
from app.core.task_context import NULL_CONTEXT, OperationCancelled, TaskContext
from app.utils.file_utils import (
    ensure_directory,
    get_extension,
    get_filename,
    temp_output_path,
)
from app.utils.libreoffice_manager import (
    LibreOfficeError,
    LibreOfficeManager,
    libreoffice_manager,
)
from app.utils.logger import get_logger
from app.utils.temp_manager import temp_manager

# python-docx lê e escreve o formato do Word sem depender de nada
# externo. Sem ele, as duas conversões de DOCX que são Python puro não
# são registradas — e DOCX → PDF, que é trabalho do LibreOffice,
# continua funcionando.
try:
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
except ImportError:  # pragma: no cover — depende do ambiente
    docx = None  # type: ignore[assignment]

DOCX_AVAILABLE = docx is not None

# O mesmo PyMuPDF do conversor de PDF da Fase 4. A tentativa em dois
# nomes se repete aqui (em vez de importar do outro módulo) para que
# TXT → PDF não passe a depender do Pillow por tabela.
try:  # PyMuPDF >= 1.24 expõe o nome novo; versões antigas, só o antigo.
    import pymupdf
except ImportError:  # pragma: no cover — depende da versão instalada
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None  # type: ignore[assignment]

PYMUPDF_AVAILABLE = pymupdf is not None

logger = get_logger("converters.document")

# Codificações tentadas na leitura de um .txt, em ordem. O BOM do
# UTF-8 é tratado primeiro (e o `utf-8-sig` lê um UTF-8 sem BOM do
# mesmo jeito); o cp1252 é o padrão histórico do Windows em português,
# onde mora a maioria dos .txt antigos com acento; e o latin-1 fecha a
# lista porque decodifica qualquer byte sem erro — pode trocar um
# caractere, mas nunca deixa de abrir o arquivo.
TEXT_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp1252", "latin-1")

# Página A4 em pontos, e a margem de ~2 cm usada no TXT → PDF.
PAGE_WIDTH, PAGE_HEIGHT = 595.0, 842.0
PAGE_MARGIN = 56.0

# Fonte monoespaçada e tamanho do TXT → PDF. "cour" é uma das fontes
# que todo leitor de PDF já tem, então o arquivo não precisa carregar
# nenhuma fonte embutida. Monoespaçada porque texto puro costuma vir
# alinhado por espaços (tabelas de "ASCII art", saída de programa,
# código) e uma fonte proporcional desmancharia esse alinhamento.
PDF_FONT = "cour"
PDF_FONT_SIZE = 10.0
PDF_LINE_HEIGHT = 1.35

# Largura de um tab ao virar espaços. O PDF não tem parada de tabulação,
# e 4 é o que a maioria dos editores usa.
TAB_WIDTH = 4

# As fontes que todo leitor de PDF já tem (as "base 14", entre elas a
# Courier usada aqui) são limitadas ao Latin-1, que cobre o português
# mas não cobre a pontuação tipográfica — travessão, aspas curvas,
# reticências, marcador de lista. Sem tradução, cada um desses vira um
# quadradinho no PDF, e um texto escrito em editor moderno fica cheio
# deles. A alternativa seria embutir uma fonte Unicode no arquivo, o que
# exigiria encontrar e carregar uma fonte do sistema — caro e frágil para
# o ganho. Traduzir para o equivalente em ASCII mantém o texto legível e
# o PDF leve. O que sobrar fora da tabela continua virando o
# quadradinho: é feio, mas é visível, e nada desaparece sem aviso.
PDF_TEXT_REPLACEMENTS = str.maketrans(
    {
        "—": "--",
        "–": "-",
        "―": "--",
        "‐": "-",
        "‑": "-",
        "“": '"',
        "”": '"',
        "„": '"',
        "″": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "′": "'",
        "…": "...",
        "•": "*",
        "→": "->",
        "←": "<-",
        "≤": "<=",
        "≥": ">=",
        "≠": "!=",
        "€": "EUR",
        "™": "(TM)",
        "\u00a0": " ",  # espaço inquebrável
        "\u2009": " ",  # espaço fino
        "\u202f": " ",  # espaço fino inquebrável
    }
)

# De quantos em quantos itens (linhas, parágrafos) o andamento é
# reportado. Um arquivo de cem mil linhas não deve disparar cem mil
# atualizações de barra de progresso.
_PROGRESS_EVERY = 200


class _DocumentError(Exception):
    """Problema no documento, com a mensagem já pronta para o usuário.

    Serve para interromper a conversão lá de dentro sem espalhar
    checagens de retorno pelo caminho — o mesmo papel que o
    `_MergeInputError` tem na junção.
    """


def read_text_file(path: str | Path) -> str:
    """Lê um arquivo de texto tentando as codificações mais prováveis.

    Um .txt não declara em que codificação foi gravado, então não há
    como saber: o que dá para fazer é tentar na ordem do mais provável
    e parar na primeira que decodificar o arquivo inteiro sem erro.
    """
    path = Path(path)
    data = path.read_bytes()
    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    # Inalcançável na prática: o latin-1 decodifica qualquer byte.
    raise _DocumentError(  # pragma: no cover
        f"Não foi possível identificar a codificação de '{get_filename(path)}'."
    )


class DocumentConverter(BaseConverter):
    """Esqueleto dos conversores de documento.

    O roteiro é o mesmo para todos: conferir a operação e o arquivo de
    origem, gravar o resultado em um temporário, mover o temporário para
    o destino e traduzir qualquer erro em uma mensagem em português. As
    subclasses entram apenas com os formatos que atendem e com o
    `_perform`, que é o trabalho em si.
    """

    #: Extensões de entrada aceitas por este conversor.
    sources: set[str] = set()

    #: Extensões de saída que este conversor sabe gravar.
    targets: set[str] = set()

    #: Nome do que este conversor produz, usado nas mensagens de erro.
    produces: str = "documento"

    #: Biblioteca/programa por trás, só para o log.
    backend: str = "?"

    @property
    def source_formats(self) -> set[str]:
        return set(self.sources)

    @property
    def target_formats(self) -> set[str]:
        return set(self.targets)

    def convert(
        self, input_path: str, output_path: str, context: TaskContext | None = None
    ) -> ConversionResult:
        context = context or NULL_CONTEXT
        source = Path(input_path)
        destination = Path(output_path)
        started_at = time.monotonic()

        if get_extension(destination) not in self.targets:
            return self._failure(
                input_path,
                f"O FileMorph ainda não sabe gravar {self.produces} em "
                f".{get_extension(destination)}.",
            )
        if not source.is_file():
            return self._failure(
                input_path, f"O arquivo '{get_filename(source)}' não foi encontrado."
            )

        temp_output: Path | None = None
        try:
            context.check_cancelled()
            ensure_directory(destination.parent)
            temp_output = temp_output_path(destination)

            self._perform(source, temp_output, context)

            temp_output.replace(destination)
            temp_output = None
        except OperationCancelled:
            raise  # não é falha: quem trata é a fila
        except _DocumentError as exc:
            return self._failure(input_path, str(exc))
        except PermissionError:
            return self._failure(
                input_path,
                "Sem permissão para gravar na pasta de destino. "
                "Escolha outra pasta nas configurações.",
            )
        except OSError as exc:
            logger.exception("Erro de sistema ao converter %s", input_path)
            detail = getattr(exc, "strerror", None) or str(exc)
            return self._failure(
                input_path, f"Não foi possível gravar o arquivo convertido ({detail})."
            )
        except Exception:  # noqa: BLE001 — a UI nunca deve receber um traceback
            logger.exception("Falha inesperada ao converter %s", input_path)
            return self._failure(
                input_path,
                "Erro inesperado ao converter este documento. Veja os logs "
                "para detalhes.",
            )
        finally:
            # Vale para os três desfechos: sucesso (aqui já é None),
            # falha e cancelamento.
            if temp_output is not None:
                temp_output.unlink(missing_ok=True)

        context.report(100)
        logger.info(
            "Conversão concluída | %s | %s -> %s | %.2fs",
            self.backend,
            get_filename(source),
            get_filename(destination),
            time.monotonic() - started_at,
        )
        return ConversionResult(
            success=True, input_path=input_path, output_path=str(destination)
        )

    def _perform(self, source: Path, temp_output: Path, context: TaskContext) -> None:
        """Faz a conversão, gravando em `temp_output`.

        Deve levantar `_DocumentError` para um problema que o usuário
        precisa entender, e deixar `OperationCancelled` subir.
        """
        raise NotImplementedError

    @staticmethod
    def _failure(input_path: str, message: str) -> ConversionResult:
        logger.warning("Conversão falhou | %s | %s", get_filename(input_path), message)
        return ConversionResult(
            success=False, input_path=input_path, error_message=message
        )


# --- DOCX <-> TXT (python-docx) -------------------------------------------


def _iter_text_blocks(document) -> list[str]:
    """Texto do documento, bloco a bloco, na ordem em que aparece.

    Percorrer o corpo do XML em vez de usar `document.paragraphs` é o que
    mantém a ordem certa quando há tabelas: os parágrafos e as tabelas
    são listas separadas na API do python-docx, e juntá-las depois
    embaralharia o documento — todas as tabelas iriam para o fim.

    As células de uma linha de tabela saem separadas por tabulação, que é
    o mais perto de "tabela" que um arquivo de texto alcança.
    """
    blocks: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            blocks.append(Paragraph(child, document).text)
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            for row in table.rows:
                blocks.append("\t".join(cell.text.strip() for cell in row.cells))
    return blocks


class DocxToTextConverter(DocumentConverter):
    """Extrai o texto de um DOCX (python-docx).

    Formatação, imagens, cabeçalho e rodapé ficam de fora, porque um
    arquivo de texto não tem onde guardá-los.
    """

    sources = {"docx"}
    targets = {"txt"}
    produces = "texto"
    backend = "python-docx"

    def _perform(self, source: Path, temp_output: Path, context: TaskContext) -> None:
        if not DOCX_AVAILABLE:  # rede de segurança: sem a lib nem é registrado
            raise _DocumentError(
                "A leitura de DOCX depende do python-docx, que não está "
                "instalado. Rode 'pip install -r requirements.txt' para "
                "habilitá-la."
            )

        try:
            document = docx.Document(str(source))
        except Exception as exc:  # noqa: BLE001 — python-docx sinaliza assim
            logger.warning("DOCX ilegível: %s (%s)", source, exc)
            raise _DocumentError(
                f"'{get_filename(source)}' não é um documento do Word válido, "
                "está corrompido ou protegido por senha."
            ) from exc

        blocks = _iter_text_blocks(document)
        total = len(blocks)
        lines: list[str] = []
        for index, text in enumerate(blocks):
            if index % _PROGRESS_EVERY == 0:
                # Ponto seguro para parar: nada foi gravado ainda.
                context.check_cancelled()
                context.report_step(index, total)
            lines.append(text)

        content = "\n".join(lines).strip()
        if not content:
            # Um DOCX só de imagens geraria um .txt vazio, e o usuário
            # ficaria sem entender o que aconteceu. Dizer o motivo é mais
            # útil do que entregar um arquivo em branco.
            raise _DocumentError(
                f"'{get_filename(source)}' não tem texto para extrair — o "
                "conteúdo parece ser apenas imagens ou objetos."
            )

        context.check_cancelled()
        temp_output.write_text(content + "\n", encoding="utf-8")


class TextToDocxConverter(DocumentConverter):
    """Monta um DOCX a partir de texto puro (python-docx).

    Uma linha do arquivo vira um parágrafo do documento, com a
    formatação padrão do Word. Não há o que inferir além disso: o .txt
    não guarda nenhuma informação de layout.
    """

    sources = {"txt"}
    targets = {"docx"}
    produces = "documento do Word"
    backend = "python-docx"

    def _perform(self, source: Path, temp_output: Path, context: TaskContext) -> None:
        if not DOCX_AVAILABLE:  # rede de segurança: sem a lib nem é registrado
            raise _DocumentError(
                "A gravação de DOCX depende do python-docx, que não está "
                "instalado. Rode 'pip install -r requirements.txt' para "
                "habilitá-la."
            )

        lines = read_text_file(source).splitlines()
        document = docx.Document()
        total = len(lines)

        for index, line in enumerate(lines):
            if index % _PROGRESS_EVERY == 0:
                context.check_cancelled()
                context.report_step(index, total)
            document.add_paragraph(line)

        context.check_cancelled()
        document.save(str(temp_output))


# --- TXT -> PDF (PyMuPDF) -------------------------------------------------


def wrap_text_lines(text: str, chars_per_line: int) -> list[str]:
    """Quebra o texto em linhas que cabem na largura da página.

    A conta é simples porque a fonte é monoespaçada: todo caractere tem
    a mesma largura, então "quantos caracteres cabem" é um número fixo,
    e não depende de quais caracteres são.

    A quebra é por palavra, como em qualquer editor. Uma palavra mais
    larga que a página inteira (um caminho de arquivo enorme, uma URL)
    é cortada no meio — é feio, mas o contrário seria deixá-la escapar
    pela borda e desaparecer do PDF.
    """
    if chars_per_line < 1:  # pragma: no cover — página absurdamente estreita
        chars_per_line = 1

    wrapped: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.replace("\t", " " * TAB_WIDTH).rstrip()
        if not line:
            wrapped.append("")
            continue

        # `None` é "ainda não comecei esta linha", diferente de "comecei e
        # está vazia". A distinção importa na indentação: uma linha que
        # começa com espaços produz palavras vazias ao ser dividida, e
        # tratá-las como "não comecei" comeria o recuo do texto.
        current: str | None = None
        for word in line.split(" "):
            while len(word) > chars_per_line:
                if current is not None:
                    wrapped.append(current)
                    current = None
                wrapped.append(word[:chars_per_line])
                word = word[chars_per_line:]

            if current is None:
                current = word
            elif len(current) + 1 + len(word) <= chars_per_line:
                current += " " + word
            else:
                wrapped.append(current)
                current = word
        wrapped.append(current if current is not None else "")

    return wrapped


class TextToPdfConverter(DocumentConverter):
    """Imprime texto puro em um PDF A4 (PyMuPDF).

    Fonte monoespaçada, margem de 2 cm, quebra de linha automática e
    quantas páginas forem necessárias.
    """

    sources = {"txt"}
    targets = {"pdf"}
    produces = "PDF"
    backend = "PyMuPDF"

    def _perform(self, source: Path, temp_output: Path, context: TaskContext) -> None:
        if not PYMUPDF_AVAILABLE:  # rede de segurança: sem a lib nem é registrado
            raise _DocumentError(
                "A gravação de PDF a partir de texto depende do PyMuPDF, que "
                "não está instalado. Rode 'pip install -r requirements.txt' "
                "para habilitá-la."
            )

        text = read_text_file(source).translate(PDF_TEXT_REPLACEMENTS)

        char_width = pymupdf.get_text_length(
            "0", fontname=PDF_FONT, fontsize=PDF_FONT_SIZE
        )
        usable_width = PAGE_WIDTH - 2 * PAGE_MARGIN
        usable_height = PAGE_HEIGHT - 2 * PAGE_MARGIN
        line_height = PDF_FONT_SIZE * PDF_LINE_HEIGHT

        lines = wrap_text_lines(text, int(usable_width / char_width))
        lines_per_page = max(1, int(usable_height / line_height))
        pages = [
            lines[start : start + lines_per_page]
            for start in range(0, len(lines), lines_per_page)
        ]
        # Um arquivo vazio não é um erro — vira um PDF de uma página em
        # branco, que é o que o documento de fato diz.
        if not pages:
            pages = [[]]

        document = pymupdf.open()
        try:
            total = len(pages)
            for number, page_lines in enumerate(pages):
                # Entre uma página e outra: nada foi gravado em disco
                # ainda, o documento só existe em memória.
                context.check_cancelled()
                page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
                if page_lines:
                    # A origem do texto é a linha de base da primeira
                    # linha, e não o topo da caixa — daí somar a altura
                    # da fonte à margem.
                    page.insert_text(
                        (PAGE_MARGIN, PAGE_MARGIN + PDF_FONT_SIZE),
                        page_lines,
                        fontname=PDF_FONT,
                        fontsize=PDF_FONT_SIZE,
                        lineheight=PDF_LINE_HEIGHT,
                    )
                context.report_step(number + 1, total)

            context.check_cancelled()
            document.save(str(temp_output))
        finally:
            document.close()


# --- PDF -> TXT (PyMuPDF) -------------------------------------------------


class PdfToTextConverter(DocumentConverter):
    """Extrai o texto de um PDF (PyMuPDF).

    Funciona com PDF de texto — o que foi gerado por um programa. Um PDF
    que é só a imagem de uma página digitalizada não tem texto nenhum
    por dentro, e reconhecê-lo exigiria OCR, que o FileMorph não faz;
    nesse caso a conversão avisa em vez de entregar um arquivo vazio.
    """

    sources = {"pdf"}
    targets = {"txt"}
    produces = "texto"
    backend = "PyMuPDF"

    def _perform(self, source: Path, temp_output: Path, context: TaskContext) -> None:
        if not PYMUPDF_AVAILABLE:  # rede de segurança: sem a lib nem é registrado
            raise _DocumentError(
                "A leitura de PDF depende do PyMuPDF, que não está instalado. "
                "Rode 'pip install -r requirements.txt' para habilitá-la."
            )

        try:
            document = pymupdf.open(source)
        except Exception as exc:  # noqa: BLE001 — PyMuPDF sinaliza assim
            logger.warning("PDF ilegível: %s (%s)", source, exc)
            raise _DocumentError(
                f"'{get_filename(source)}' não é um PDF válido ou está "
                "corrompido."
            ) from exc

        try:
            if document.needs_pass:
                raise _DocumentError(
                    f"'{get_filename(source)}' está protegido por senha. "
                    "Remova a proteção antes de converter."
                )
            page_count = document.page_count
            if page_count == 0:
                raise _DocumentError(f"'{get_filename(source)}' não tem páginas.")

            # As páginas são separadas por uma linha em branco. Um
            # marcador do tipo "--- página 2 ---" seria texto que o
            # documento não tem, e um caractere de quebra de página
            # apareceria como um quadradinho no Bloco de Notas.
            chunks: list[str] = []
            for number in range(page_count):
                context.check_cancelled()
                chunks.append(document[number].get_text().strip())
                context.report_step(number + 1, page_count)
        finally:
            document.close()

        content = "\n\n".join(chunk for chunk in chunks if chunk).strip()
        if not content:
            raise _DocumentError(
                f"'{get_filename(source)}' não tem texto para extrair. Ele "
                "parece ser um documento digitalizado (imagens de páginas), e "
                "o FileMorph não faz reconhecimento de texto."
            )

        context.check_cancelled()
        temp_output.write_text(content + "\n", encoding="utf-8")


# --- DOCX -> PDF (LibreOffice) --------------------------------------------


class DocxToPdfConverter(DocumentConverter):
    """Converte um DOCX em PDF preservando o layout (LibreOffice headless).

    Único conversor de documento que depende de um programa externo, e o
    único que é registrado condicionalmente: sem LibreOffice instalado,
    "PDF" não aparece no seletor de formato para um DOCX.
    """

    sources = {"docx"}
    targets = {"pdf"}
    produces = "PDF"
    backend = "LibreOffice"

    def __init__(self, manager: LibreOfficeManager | None = None) -> None:
        # O gerenciador é injetável para que os testes possam usar um
        # LibreOffice de mentira e exercitar a montagem do comando, o
        # cancelamento e o tratamento de erro sem depender do programa
        # estar instalado na máquina que roda a suíte.
        self._manager = manager or libreoffice_manager

    def _perform(self, source: Path, temp_output: Path, context: TaskContext) -> None:
        if not self._manager.is_available():  # rede de segurança
            raise _DocumentError(
                "A conversão de DOCX para PDF depende do LibreOffice, que não "
                "foi encontrado nesta máquina. Instale-o para habilitá-la."
            )

        # O LibreOffice não aceita um nome de arquivo de saída, só uma
        # pasta — então ele grava em uma sessão temporária e o resultado
        # é movido de lá para o temporário do destino, que é quem vira o
        # arquivo final. A sessão é apagada nos dois desfechos (item 24).
        session_id = temp_manager.new_session()
        try:
            produced = self._manager.convert(
                source, "pdf", temp_manager.session_dir(session_id), context
            )
            # `move` e não `replace`: a pasta temporária do sistema e a
            # pasta de destino do usuário podem estar em discos
            # diferentes, e aí renomear não funciona.
            shutil.move(str(produced), str(temp_output))
        except LibreOfficeError as exc:
            # A mensagem já vem traduzida pelo gerenciador.
            raise _DocumentError(str(exc)) from exc
        finally:
            temp_manager.cleanup(session_id)
