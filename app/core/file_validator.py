"""
Validação de extensões de arquivo.

Esta lista reflete os formatos que o FileMorph tem como alvo do
projeto (para que o drag-and-drop já saiba reconhecer um PNG ou um
MP4, por exemplo), mas isso é independente de já existir ou não um
conversor implementado para eles — essa segunda pergunta é respondida
pela camada de compatibilidade em `converter.py` / `merger.py`.
"""

from __future__ import annotations

from pathlib import Path

KNOWN_EXTENSIONS: dict[str, str] = {
    # Imagens
    "png": "imagem",
    "jpg": "imagem",
    "jpeg": "imagem",
    "webp": "imagem",
    "bmp": "imagem",
    "tiff": "imagem",
    "tif": "imagem",
    "gif": "imagem",
    # PDF
    "pdf": "pdf",
    # Documentos
    "docx": "documento",
    "txt": "documento",
    # Áudio
    "mp3": "audio",
    "wav": "audio",
    "flac": "audio",
    "ogg": "audio",
    "m4a": "audio",
    # Vídeo
    "mp4": "video",
    "mkv": "video",
    "avi": "video",
    "mov": "video",
    "webm": "video",
    # Planilhas
    "xlsx": "planilha",
    "csv": "planilha",
}


def is_known_extension(path: str | Path) -> bool:
    """True se a extensão do arquivo é reconhecida pelo FileMorph,
    independentemente de já haver conversão implementada para ela."""
    ext = Path(path).suffix.lower().lstrip(".")
    return ext in KNOWN_EXTENSIONS


def get_file_category(path: str | Path) -> str | None:
    """Retorna a categoria do arquivo ('imagem', 'pdf', 'documento',
    'audio', 'video', 'planilha') ou None se a extensão não é conhecida."""
    ext = Path(path).suffix.lower().lstrip(".")
    return KNOWN_EXTENSIONS.get(ext)


def validate_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    """Separa uma lista de caminhos em (válidos, inválidos).

    Um caminho é válido quando existe no disco, é um arquivo (não uma
    pasta) e tem extensão conhecida. Arquivos inválidos devem gerar
    uma mensagem clara na UI, nunca ser adicionados
    silenciosamente nem travar a aplicação.
    """
    valid: list[str] = []
    invalid: list[str] = []

    for raw_path in paths:
        p = Path(raw_path)
        if p.is_file() and is_known_extension(p):
            valid.append(str(p))
        else:
            invalid.append(str(p))

    return valid, invalid
