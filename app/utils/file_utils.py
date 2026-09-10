"""
Utilitários genéricos para manipulação de caminhos e arquivos.

Usado tanto pela UI (para exibir tamanho/ícone/extensão nos cards da
lista de arquivos) quanto pelo core (para gerar nomes de saída sem
sobrescrever arquivos existentes).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4


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
    junto com o fluxo de "arquivo já existe" da UI (item 21).
    """
    output_dir = Path(output_dir)
    ext = new_extension.lower().lstrip(".")
    return output_dir / f"{base_name}.{ext}"


def get_unique_path(path: str | Path) -> Path:
    """Se `path` já existir, retorna uma variante com sufixo numérico
    (' (1)', ' (2)', ...) até encontrar um caminho livre.

    Usado quando o usuário escolhe "Criar cópia" no conflito de nomes
    (item 21), em vez de substituir o arquivo existente.
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


def ensure_directory(path: str | Path) -> Path:
    """Garante que o diretório exista, criando-o se necessário."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


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
    se importam com o nome do arquivo, mas o FFmpeg (Fase 6) descobre o
    formato de saída *pela extensão* — um temporário terminado em
    '.filemorph-tmp' o faria recusar a conversão antes de começar.
    """
    destination = Path(destination)
    marker = f".{destination.name}.{uuid4().hex[:8]}{TEMP_WRITE_SUFFIX}"
    if keep_extension:
        marker += destination.suffix
    return destination.with_name(marker)
