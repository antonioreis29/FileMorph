"""
Utilitários genéricos para manipulação de caminhos e arquivos.

Usado tanto pela UI (para exibir tamanho/ícone/extensão nos cards da
lista de arquivos) quanto pelo core (para gerar nomes de saída sem
sobrescrever arquivos existentes).
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from uuid import uuid4

from app.utils.logger import get_logger

logger = get_logger("utils.file_utils")


def get_extension(path: str | Path) -> str:
    """Retorna a extensão em minúsculas, sem o ponto. Ex.: 'foto.PNG' -> 'png'."""
    return Path(path).suffix.lower().lstrip(".")


def get_filename(path: str | Path) -> str:
    """Retorna o nome do arquivo com extensão (sem o diretório)."""
    return Path(path).name


def get_stem(path: str | Path) -> str:
    """Retorna o nome do arquivo sem extensão."""
    return Path(path).stem


def format_file_size(num_bytes: int) -> str:
    """Formata um tamanho em bytes de forma legível: '2.4 MB', '318 KB' etc."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def get_file_size_display(path: str | Path) -> str:
    """Lê o tamanho do arquivo no disco e retorna já formatado. Retorna
    '—' se o arquivo não existir ou não puder ser lido."""
    try:
        num_bytes = Path(path).stat().st_size
    except OSError:
        return "—"
    return format_file_size(num_bytes)


def resolve_output_path(
    output_dir: str | Path, base_name: str, new_extension: str
) -> Path:
    """Monta o caminho de saída preservando o nome original.

    Ex.: base_name='foto_viagem', new_extension='jpg', output_dir=X
         -> X/foto_viagem.jpg

    Não verifica conflitos — isso é responsabilidade de quem chama,
    junto com o fluxo de "arquivo já existe" da UI.
    """
    output_dir = Path(output_dir)
    ext = new_extension.lower().lstrip(".")
    return output_dir / f"{base_name}.{ext}"


def get_unique_path(path: str | Path) -> Path:
    """Se `path` já existir, retorna uma variante com sufixo numérico
    (' (1)', ' (2)', ...) até encontrar um caminho livre.

    Só olha o disco. Para escolher os destinos de um lote inteiro, em que
    dois arquivos podem disputar o mesmo nome antes de qualquer um deles
    existir, quem decide é o `OutputPlanner` (`app/core/output_planner.py`).
    """
    path = Path(path)
    if not path.exists():
        return path

    stem, suffix, parent = path.stem, path.suffix, path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def is_same_file(first: str | Path, second: str | Path) -> bool:
    """True se os dois caminhos apontam para o mesmo arquivo no disco.

    Comparar os textos não basta no Windows, onde `C:\\Docs\\a.pdf` e
    `c:/docs/A.PDF` são o mesmo arquivo. Serve para impedir que o
    resultado de uma operação seja gravado por cima da própria origem.
    Um caminho que ainda não existe nunca é o mesmo arquivo — para esse
    caso existe `refers_to_same_path`.
    """
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def path_key(path: str | Path) -> str:
    """Uma chave de comparação para caminhos, existam eles ou não.

    Dois textos diferentes podem nomear o mesmo lugar: `C:\\Docs\\A.PDF`
    e `c:/docs/a.pdf` são o mesmo arquivo no Windows, e um nome curto
    como `SISTEM~2` é o mesmo diretório que o nome longo. `realpath`
    expande o nome curto e os atalhos do caminho (inclusive quando o
    arquivo final ainda não existe, resolvendo a parte que existe), e
    `normcase` iguala maiúsculas e barras no Windows. Em outros sistemas
    `normcase` não mexe em nada, porque lá a diferença de maiúsculas é
    diferença de arquivo.
    """
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))


def refers_to_same_path(first: str | Path, second: str | Path) -> bool:
    """True se os dois caminhos são o mesmo lugar no disco.

    Com os dois arquivos existindo, quem responde é o sistema de arquivos
    (`is_same_file`), o que cobre até um link físico. Quando algum deles
    ainda não existe — o destino de uma gravação, tipicamente —, a
    resposta vem da comparação normalizada de `path_key`.
    """
    if is_same_file(first, second):
        return True
    return path_key(first) == path_key(second)


def ensure_directory(path: str | Path) -> Path:
    """Garante que o diretório exista, criando-o se necessário."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_unique_directory(path: str | Path) -> Path:
    """Cria uma pasta nova com o nome pedido, ou com sufixo numérico.

    Serve às conversões que produzem uma pasta de arquivos (as páginas de
    um PDF, as abas de uma planilha). Verificar se o nome está livre e só
    depois criar a pasta deixaria uma janela em que duas conversões do
    mesmo lote, rodando em paralelo, escolhem o mesmo nome. Aqui a própria
    criação é a verificação: `mkdir` sem `exist_ok` falha se o nome já
    existir — seja pasta, seja arquivo —, e o sistema de arquivos garante
    que só uma das duas consegue criá-la.
    """
    path = Path(path)
    ensure_directory(path.parent)
    stem, suffix, parent = path.stem, path.suffix, path.parent
    candidate, counter = path, 0
    while True:
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            counter += 1
            candidate = parent / f"{stem} ({counter}){suffix}"


def page_destinations(destination: str | Path, page_count: int) -> tuple[Path | None, list[Path]]:
    """Onde cada página vai ser gravada, e a subpasta criada para elas.

    Uma página: exatamente o caminho pedido, que já passou pelo fluxo de
    conflito de nomes da interface, e nenhuma pasta nova. Várias páginas:
    uma subpasta nova com o nome do documento (`relatorio/relatorio_p01.png`),
    que volta junto para que uma falha consiga removê-la.
    """
    destination = Path(destination)
    if page_count == 1:
        ensure_directory(destination.parent)
        return None, [destination]

    stem = get_stem(destination)
    folder = create_unique_directory(destination.parent / stem)
    width = max(2, len(str(page_count)))
    return folder, [
        folder / f"{stem}_p{number:0{width}d}{destination.suffix}"
        for number in range(1, page_count + 1)
    ]


def discard_partial_outputs(
    written: Iterable[str | Path], created_folder: str | Path | None = None
) -> None:
    """Desfaz o que uma conversão de várias saídas já tinha gravado.

    Serve às conversões que produzem uma pasta de arquivos — as páginas
    de um PDF, as abas de uma planilha — quando elas falham ou são
    canceladas no meio: nenhum arquivo fica pela metade na pasta do
    usuário, e a subpasta que a própria conversão criou sai junto.

    A pasta vem por parâmetro, e não deduzida dos arquivos gravados, por
    dois motivos. O primeiro é o caso em que nada chegou a ser gravado:
    cancelar antes da primeira página deixava a subpasta vazia para
    trás, porque não havia arquivo nenhum de onde tirar o caminho dela.
    O segundo é segurança: deduzida, a "pasta" de uma saída única seria
    a própria pasta de destino do usuário. Só a pasta criada pela
    conversão é candidata a sair, e mesmo ela apenas se tiver ficado
    vazia — `rmdir` recusa uma pasta com conteúdo.
    """
    for path in written:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:  # pragma: no cover — arquivo em uso, por exemplo
            logger.warning("Não foi possível remover o arquivo parcial %s", path)
    if created_folder is None:
        return
    try:
        Path(created_folder).rmdir()
    except OSError:
        # Não estava vazia (alguém gravou algo ali durante a conversão)
        # ou já não existe: nos dois casos, fica como está.
        pass


# Sufixo dos arquivos temporários de gravação. Fica em um só lugar para
# que a limpeza (e os testes) saibam reconhecê-los.
TEMP_WRITE_SUFFIX = ".filemorph-tmp"


def temp_output_path(destination: str | Path, keep_extension: bool = False) -> Path:
    """Caminho temporário ao lado do destino final, para gravação atômica.

    Os conversores escrevem primeiro nesse arquivo e só então o movem
    para o nome definitivo: assim uma falha no meio da gravação não
    deixa arquivo truncado nem destrói um arquivo bom que já ocupasse o
    nome de destino. O trecho aleatório evita que duas conversões do
    mesmo lote, rodando em paralelo, disputem o mesmo temporário.

    `keep_extension` mantém a extensão do destino no fim do nome
    temporário. Pillow e pypdf recebem o formato como parâmetro e não
    se importam com o nome do arquivo, mas o FFmpeg descobre o
    formato de saída *pela extensão* — um temporário terminado em
    '.filemorph-tmp' o faria recusar a conversão antes de começar.
    """
    destination = Path(destination)
    marker = f".{destination.name}.{uuid4().hex[:8]}{TEMP_WRITE_SUFFIX}"
    if keep_extension:
        marker += destination.suffix
    return destination.with_name(marker)
