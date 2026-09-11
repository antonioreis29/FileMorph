"""
Conversores de planilha (FASE 9 do briefing).

Três caminhos:

- `XlsxToCsvConverter`      — XLSX → CSV, com openpyxl.
- `CsvToXlsxConverter`      — CSV → XLSX, com openpyxl.
- `SpreadsheetToPdfConverter` — XLSX → PDF, com LibreOffice headless.

A mecânica de gravação (temporário ao lado do destino, erro traduzido,
cancelamento) é herdada de `DocumentConverter`, da Fase 7: planilha e
documento têm exatamente o mesmo roteiro por dentro, e manter duas
cópias dele seria manter dois lugares para o mesmo cuidado dar errado.

## As três decisões que definem se o resultado é utilizável

**1. A planilha de várias abas vira uma pasta de CSVs.** Um arquivo CSV
guarda uma tabela, e uma pasta de trabalho guarda quantas quiser.
Converter só a aba ativa e calar sobre as outras seria perder dados sem
avisar. A saída segue a mesma regra que o PDF de várias páginas já usa
desde a Fase 4: uma aba só vira exatamente o arquivo pedido; várias
viram uma subpasta com o nome da planilha, um CSV por aba — **incluindo
as abas ocultas**, que são onde costuma morar a tabela de apoio das
fórmulas, e cujo nome vai no arquivo para ninguém receber um CSV sem
saber de onde veio.

**2. O CSV é escrito no dialeto que o Excel desta máquina escreve.**
Ponto e vírgula como separador e vírgula como decimal. Parece
arbitrário, e é o oposto: o Excel em português **escreve e espera**
assim, e é nele que este arquivo vai ser aberto. Um CSV separado por
vírgula, que é o dialeto internacional, abre no Excel brasileiro com
tudo empilhado na coluna A — o usuário veria um arquivo quebrado e
culparia o FileMorph, com razão. O BOM do UTF-8 vai junto pelo mesmo
motivo: sem ele o Excel ignora a codificação e come os acentos.

A direção contrária aceita os dois dialetos, então converter um CSV
baixado da internet (vírgula, ponto decimal) funciona igual.

**3. Vindo do CSV, só vira número o que não pode ser confundido.** Este
é o cuidado mais importante do módulo, porque é aqui que planilha
costuma corromper dado silenciosamente:

- `007` e `01310-100` continuam texto. Transformá-los em número comeria
  o zero à esquerda — é o defeito clássico que estraga CEP, código de
  produto e número de telefone.
- `03/04/2024` continua texto. Não há como saber se é 3 de abril ou 4 de
  março, e chutar erra em metade dos arquivos. Melhor entregar o que
  estava escrito do que uma data errada com cara de certa.
- `=SOMA(A1:A9)` continua texto, e não vira fórmula. Uma planilha que
  executa o que vinha escrito num arquivo de texto é uma porta de
  entrada conhecida para conteúdo malicioso (a "injeção em CSV"), além
  de não ser o que o arquivo dizia.
- Sobra o que é inequívoco: `42`, `-3`, `1,5`, `2.75`. Esses viram
  número de verdade, que é o que permite somar e ordenar no Excel.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from pathlib import Path

from app.converters.document_converter import (
    ConversionProblem,
    DocumentConverter,
    LibreOfficeToPdfConverter,
    read_text_file,
)
from app.core.task_context import TaskContext
from app.utils.file_utils import (
    ensure_directory,
    get_filename,
    get_stem,
    get_unique_path,
    temp_output_path,
)
from app.utils.logger import get_logger

# O openpyxl lê e escreve XLSX sem depender de nada externo. Sem ele, as
# duas conversões entre XLSX e CSV não são registradas — e XLSX → PDF,
# que é trabalho do LibreOffice, continua funcionando.
try:
    import openpyxl
except ImportError:  # pragma: no cover — depende do ambiente
    openpyxl = None  # type: ignore[assignment]

OPENPYXL_AVAILABLE = openpyxl is not None

logger = get_logger("converters.spreadsheet")

# O dialeto que o Excel em português escreve e espera. Ver a decisão 2 no
# cabeçalho deste módulo.
CSV_DELIMITER = ";"
CSV_DECIMAL = ","

# Separadores aceitos na leitura, na ordem em que são testados. O
# ponto e vírgula vem primeiro porque é o que sai daqui e do Excel
# brasileiro; a vírgula é o dialeto internacional; tabulação e barra
# vertical aparecem em exportações de banco de dados.
CSV_CANDIDATE_DELIMITERS = (";", ",", "\t", "|")

# Codificação de saída: UTF-8 **com** BOM, porque é o que faz o Excel
# reconhecer os acentos em vez de tratar o arquivo como ANSI.
CSV_ENCODING = "utf-8-sig"

# De quantas em quantas linhas o andamento é reportado. Uma planilha de
# cem mil linhas não deve disparar cem mil atualizações de barra.
_PROGRESS_EVERY = 200

# Um número inequívoco: sinal opcional, dígitos, e no máximo uma casa
# decimal separada por ponto ou vírgula. Zero à esquerda é recusado de
# propósito (ver a decisão 3), e por isso "0" e "0,5" têm regra própria.
_NUMBER_RE = re.compile(r"^[+-]?(?:0|[1-9]\d*)(?:[.,]\d+)?$")

# Separador de milhar, que precisa ser recusado: "1.234" pode ser mil
# duzentos e trinta e quatro ou um e duzentos e trinta e quatro
# milésimos, dependendo do país de quem gravou o arquivo.
_THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}([.,]\d{3})+$")


# --- Leitura e escrita de valores -----------------------------------------


def format_cell(value: object) -> str:
    """Transforma o valor de uma célula no texto que vai para o CSV.

    As datas saem em formato ISO (`2024-03-04`) porque é o único que não
    é ambíguo e que o Excel reconhece como data em qualquer idioma. Os
    números saem com vírgula decimal, no dialeto descrito no cabeçalho —
    e um número inteiro guardado como decimal (o Excel faz isso com
    frequência) sai sem o `.0` pendurado, que não estava na planilha.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        # Antes de `int`: em Python, `bool` é uma subclasse de `int`, e
        # sem este caso True viraria "1".
        return "VERDADEIRO" if value else "FALSO"
    if isinstance(value, datetime):
        if value.time() == time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        # O Excel guarda duração como fração de dia; o openpyxl devolve
        # timedelta. Em texto, o total em horas é o que se entende.
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value).replace(".", CSV_DECIMAL)
    if isinstance(value, int):
        return str(value)
    return str(value)


def parse_cell(text: str) -> object:
    """Transforma o texto de um campo do CSV no valor que vai para a célula.

    Devolve `int` ou `float` só quando o texto não pode significar outra
    coisa; em qualquer dúvida, devolve o próprio texto. As regras e os
    motivos estão na decisão 3 do cabeçalho deste módulo.
    """
    stripped = text.strip()
    if not stripped:
        return None

    if _THOUSANDS_RE.match(stripped):
        return text
    if not _NUMBER_RE.match(stripped):
        return text

    normalized = stripped.replace(CSV_DECIMAL, ".")
    try:
        if "." in normalized:
            return float(normalized)
        return int(normalized)
    except ValueError:  # pragma: no cover — a expressão já garantiu o formato
        return text


def sniff_delimiter(sample: str) -> str:
    """Descobre qual caractere separa os campos deste CSV.

    O arquivo não declara isso em lugar nenhum, então a escolha é por
    evidência: vale o separador que divide as primeiras linhas em um
    número de colunas **igual e maior que um**. Um separador errado não
    dá erro de leitura — ele só entrega tudo numa coluna só, ou quebra as
    linhas em lugares diferentes —, e é essa diferença que a contagem
    detecta.
    """
    linhas = [linha for linha in sample.splitlines() if linha.strip()][:20]
    if not linhas:
        return CSV_DELIMITER

    melhor, melhor_colunas = CSV_DELIMITER, 1
    for candidato in CSV_CANDIDATE_DELIMITERS:
        try:
            colunas = [
                len(campos)
                for campos in csv.reader(linhas, delimiter=candidato)
            ]
        except csv.Error:  # pragma: no cover — linha malformada
            continue
        if not colunas or len(set(colunas)) != 1:
            continue
        if colunas[0] > melhor_colunas:
            melhor, melhor_colunas = candidato, colunas[0]

    return melhor


def read_csv_rows(path: Path) -> tuple[list[list[str]], str]:
    """As linhas do CSV e o separador que foi reconhecido.

    A codificação é descoberta do mesmo jeito que num .txt (ver
    `read_text_file`, da Fase 7): um CSV também não declara a sua.
    """
    texto = read_text_file(path)
    delimiter = sniff_delimiter(texto[:8192])
    # `io.StringIO` em vez de reabrir o arquivo: o texto já foi
    # decodificado, e o módulo csv precisa de quebras de linha
    # normalizadas para não engolir a última linha sem \n.
    leitor = csv.reader(io.StringIO(texto, newline=""), delimiter=delimiter)
    try:
        return [linha for linha in leitor], delimiter
    except csv.Error as exc:
        raise ConversionProblem(
            f"'{get_filename(path)}' não pôde ser lido como CSV ({exc})."
        ) from exc


# --- XLSX -> CSV ----------------------------------------------------------


class XlsxToCsvConverter(DocumentConverter):
    """Extrai as abas de uma planilha para CSV (openpyxl).

    Formatação, fórmulas, gráficos e imagens ficam de fora: um CSV é uma
    tabela de texto e não tem onde guardá-los. O que sai de uma célula
    com fórmula é o **último valor calculado** e gravado no arquivo — o
    openpyxl não calcula fórmula, e nenhuma biblioteca de leitura
    calcula. Uma planilha gerada por um programa que nunca abriu o Excel
    pode não ter esses valores guardados, e aí a célula sai vazia; é uma
    propriedade do arquivo, não da conversão.
    """

    sources = {"xlsx"}
    targets = {"csv"}
    produces = "CSV"
    backend = "openpyxl"

    def _perform(
        self,
        source: Path,
        temp_output: Path,
        destination: Path,
        context: TaskContext,
    ) -> Path | None:
        if not OPENPYXL_AVAILABLE:  # rede de segurança: sem a lib nem é registrado
            raise ConversionProblem(
                "A leitura de XLSX depende do openpyxl, que não está "
                "instalado. Rode 'pip install -r requirements.txt' para "
                "habilitá-la."
            )

        # `read_only` evita carregar a planilha inteira na memória, e
        # `data_only` pede o valor calculado das fórmulas em vez do texto
        # da fórmula.
        try:
            workbook = openpyxl.load_workbook(
                source, read_only=True, data_only=True
            )
        except Exception as exc:  # noqa: BLE001 — openpyxl sinaliza assim
            logger.warning("XLSX ilegível: %s (%s)", source, exc)
            raise ConversionProblem(
                f"'{get_filename(source)}' não é uma planilha válida, está "
                "corrompida ou protegida por senha."
            ) from exc

        try:
            # Aba oculta entra também. Ela costuma guardar a tabela de
            # apoio que as fórmulas consultam, e deixá-la de fora seria
            # perder dado sem dizer nada — o nome do arquivo diz de qual
            # aba cada CSV veio, então nada aparece sem explicação.
            abas = list(workbook.worksheets)
            if not abas:
                raise ConversionProblem(
                    f"'{get_filename(source)}' não tem nenhuma aba para converter."
                )

            destinos = self._sheet_destinations(abas, temp_output, destination)
            escritos: list[Path] = []
            try:
                for indice, (aba, destino) in enumerate(zip(abas, destinos)):
                    # Entre uma aba e outra é ponto seguro para parar.
                    context.check_cancelled()
                    self._write_sheet(aba, destino, context)
                    escritos.append(destino)
                    context.report_step(indice + 1, len(abas))
            except BaseException:
                # Uma conversão interrompida no meio não deixa CSVs pela
                # metade — nem a subpasta vazia que os abrigava.
                self._discard(escritos)
                raise
        finally:
            workbook.close()

        if escritos == [temp_output]:
            # Aba única: o resultado é o temporário, e a classe base o
            # move para o destino definitivo.
            return None
        return escritos[0].parent

    def _sheet_destinations(
        self, abas: list, temp_output: Path, destination: Path
    ) -> list[Path]:
        """Onde cada aba vai ser gravada.

        Uma aba: o arquivo temporário, que a classe base move para o
        destino pedido — é o caminho que já passou pelo fluxo de conflito
        de nomes da interface. Várias abas: uma subpasta nova com o nome
        da planilha, e o nome de cada aba no arquivo correspondente, para
        que dê para saber de onde cada CSV veio.
        """
        if len(abas) == 1:
            return [temp_output]

        stem = get_stem(destination)
        pasta = get_unique_path(destination.parent / stem)
        ensure_directory(pasta)
        # O número mantém a ordem das abas visível e garante nomes
        # distintos: dois títulos diferentes podem virar o mesmo nome
        # depois de tirar os caracteres que não servem em arquivo.
        return [
            pasta / f"{stem}_{numero:02d}_{self._safe_name(aba.title)}{destination.suffix}"
            for numero, aba in enumerate(abas, start=1)
        ]

    @staticmethod
    def _safe_name(title: str) -> str:
        """O nome da aba reduzido ao que serve de nome de arquivo.

        Nomes de aba aceitam espaço, acento e pontuação que o sistema de
        arquivos recusa (ou que tornam o nome incômodo de digitar). Uma
        aba sem nome utilizável cai em um rótulo genérico, em vez de
        gerar um arquivo chamado só `.csv`.
        """
        limpo = re.sub(r"[^\w.-]+", "_", title, flags=re.UNICODE).strip("_")
        return limpo or "aba"

    def _write_sheet(self, aba, destino: Path, context: TaskContext) -> None:
        """Grava uma aba, de forma atômica, no caminho indicado."""
        temporario = temp_output_path(destino)
        try:
            with open(temporario, "w", encoding=CSV_ENCODING, newline="") as arquivo:
                escritor = csv.writer(arquivo, delimiter=CSV_DELIMITER)
                for numero, linha in enumerate(self._rows(aba)):
                    if numero % _PROGRESS_EVERY == 0:
                        context.check_cancelled()
                    escritor.writerow(linha)
            temporario.replace(destino)
        except BaseException:
            temporario.unlink(missing_ok=True)
            raise

    @staticmethod
    def _rows(aba) -> Iterator[list[str]]:
        """As linhas da aba em texto, sem as linhas vazias do fim.

        O Excel guarda com frequência uma "dimensão" maior do que o dado
        de verdade — basta alguém ter apagado o conteúdo de uma célula
        distante. Sem este corte, o CSV terminaria com centenas de linhas
        de ponto e vírgula.
        """
        pendentes: list[list[str]] = []
        for linha in aba.iter_rows(values_only=True):
            campos = [format_cell(valor) for valor in linha]
            while campos and campos[-1] == "":
                campos.pop()
            if not campos:
                # Pode ser uma linha em branco no meio da tabela, que
                # conta, ou o rabo vazio da planilha, que não. Só se sabe
                # ao encontrar (ou não) a próxima linha com conteúdo.
                pendentes.append([])
                continue
            yield from pendentes
            pendentes.clear()
            yield campos

    @staticmethod
    def _discard(escritos: list[Path]) -> None:
        pastas = {caminho.parent for caminho in escritos}
        for caminho in escritos:
            try:
                caminho.unlink(missing_ok=True)
            except OSError:  # pragma: no cover — arquivo em uso
                logger.warning("Não foi possível remover o CSV parcial %s", caminho)
        for pasta in pastas:
            try:
                pasta.rmdir()  # só remove se tiver ficado vazia
            except OSError:
                pass


# --- CSV -> XLSX ----------------------------------------------------------


class CsvToXlsxConverter(DocumentConverter):
    """Monta uma planilha a partir de um CSV (openpyxl).

    O separador e a codificação do arquivo de entrada são descobertos por
    evidência (ver `sniff_delimiter` e `read_text_file`), e o conteúdo de
    cada campo só vira número quando não pode significar outra coisa.
    """

    sources = {"csv"}
    targets = {"xlsx"}
    produces = "planilha"
    backend = "openpyxl"

    def _perform(
        self,
        source: Path,
        temp_output: Path,
        destination: Path,
        context: TaskContext,
    ) -> Path | None:
        if not OPENPYXL_AVAILABLE:  # rede de segurança: sem a lib nem é registrado
            raise ConversionProblem(
                "A gravação de XLSX depende do openpyxl, que não está "
                "instalado. Rode 'pip install -r requirements.txt' para "
                "habilitá-la."
            )

        linhas, delimiter = read_csv_rows(source)
        logger.debug("CSV '%s' lido com separador '%s'", get_filename(source), delimiter)

        workbook = openpyxl.Workbook(write_only=True)
        try:
            # `write_only` grava linha a linha em vez de montar a planilha
            # toda na memória, o que importa num CSV de centenas de
            # milhares de linhas.
            aba = workbook.create_sheet(title=self._sheet_title(source))
            total = len(linhas)
            for numero, campos in enumerate(linhas):
                if numero % _PROGRESS_EVERY == 0:
                    context.check_cancelled()
                    context.report_step(numero, total)
                aba.append([self._cell(aba, campo) for campo in campos])

            context.check_cancelled()
            workbook.save(temp_output)
        finally:
            workbook.close()
        return None

    @staticmethod
    def _sheet_title(source: Path) -> str:
        """Nome da aba: o do arquivo, dentro do que o Excel aceita.

        O limite é 31 caracteres, e os caracteres `[]:*?/\\` são
        proibidos — um nome inválido faz o openpyxl recusar a gravação.
        """
        limpo = re.sub(r"[\[\]:*?/\\]", "-", get_stem(source)).strip()
        return (limpo[:31] or "Planilha")

    @staticmethod
    def _cell(aba, text: str):
        """A célula pronta para a planilha, com o tipo já decidido.

        Um texto que começa com `=` recebe o tipo "string" à força.
        Sem isso o openpyxl o gravaria como fórmula, e a planilha
        passaria a executar o que era só texto num arquivo (ver a
        decisão 3 no cabeçalho deste módulo).

        A célula precisa nascer ligada à aba: uma `WriteOnlyCell` sem
        dono não consegue nem guardar o próprio valor.
        """
        valor = parse_cell(text)
        celula = openpyxl.cell.cell.WriteOnlyCell(aba, value=valor)
        if isinstance(valor, str) and valor.startswith("="):
            celula.data_type = "s"
        return celula


# --- XLSX -> PDF (LibreOffice) --------------------------------------------


class SpreadsheetToPdfConverter(LibreOfficeToPdfConverter):
    """Converte uma planilha em PDF (LibreOffice headless).

    Reaproveita inteiro o caminho que o DOCX já usava desde a Fase 7 — o
    programa externo é o mesmo, e a mecânica de pasta temporária e
    gravação atômica também.

    Vale o aviso que vale para imprimir planilha em qualquer programa: o
    PDF sai com a paginação que o arquivo pedir, e uma planilha larga
    demais para a página é cortada em várias. Quem controla isso é a
    configuração de impressão guardada dentro da própria planilha, não o
    FileMorph.
    """

    sources = {"xlsx"}
    familia = "planilha"
