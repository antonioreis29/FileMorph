"""
Diagnóstico da instalação: o que está disponível nesta máquina, e por quê.

Duas perguntas aparecem sempre que alguém ajuda um usuário do FileMorph:
"qual versão você tem?" e "por que a opção X não aparece?". Este módulo
junta as respostas num relatório só — versão do aplicativo, Windows, onde
ficam as configurações e os logs, e a situação dos dois programas externos
opcionais —, que a janela de diagnóstico mostra e copia para a área de
transferência.

Também é daqui que vêm as explicações curtas de dependência que a janela
principal mostra ao lado dos arquivos (`dependency_hint`): um MP3 na lista
sem FFmpeg instalado, um DOCX que não pode virar PDF sem o LibreOffice.

Livre de Qt: a versão do Qt, quando interessa, é informada por quem chama.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.core.file_validator import get_file_category
from app.utils.ffmpeg_manager import (
    FFMPEG_DOWNLOAD_URL,
    SOURCE_BUNDLED,
    SOURCE_CONFIGURED,
    SOURCE_PATH,
    FFmpegManager,
    ffmpeg_manager,
)
from app.utils.libreoffice_manager import (
    LIBREOFFICE_DOWNLOAD_URL,
    LibreOfficeManager,
    libreoffice_manager,
)
from app.version import APP_NAME, __version__

# O que cada programa externo habilita, na linguagem de quem usa o aplicativo.
FFMPEG_FEATURES: tuple[str, ...] = (
    "Converter áudio: MP3, WAV, FLAC, OGG e M4A",
    "Converter vídeo: MP4, MKV e WEBM (também a partir de AVI e MOV)",
    "Extrair o áudio de um vídeo",
)
LIBREOFFICE_FEATURES: tuple[str, ...] = (
    "Converter DOCX (Word) em PDF",
    "Converter XLSX (Excel) em PDF",
    "Usar DOCX e XLSX no modo Juntar",
)

_SOURCE_LABELS = {
    SOURCE_BUNDLED: "incluído no FileMorph",
    SOURCE_CONFIGURED: "definido nas configurações",
    SOURCE_PATH: "encontrado no PATH do Windows",
}


@dataclass(frozen=True)
class DependencyInfo:
    """A situação de um programa externo opcional."""

    name: str
    available: bool
    version: str | None
    path: str | None
    source: str | None
    features: tuple[str, ...]
    download_url: str
    # True quando o programa já estava presente na abertura do aplicativo e
    # as conversões dele estão no seletor. Encontrado mas não ativo quer
    # dizer que foi instalado com o FileMorph aberto: falta reiniciar.
    active: bool = False
    # Formatos que a instalação encontrada consegue gerar (só o FFmpeg varia).
    offered_formats: tuple[str, ...] = ()

    def status_text(self) -> str:
        """Uma frase para a janela de diagnóstico."""
        if not self.available:
            return f"{self.name} não foi encontrado nesta máquina."
        details = f"versão {self.version or 'desconhecida'}"
        if self.source in _SOURCE_LABELS:
            details += f", {_SOURCE_LABELS[self.source]}"
        if not self.active:
            return (
                f"{self.name} encontrado ({details}), mas ainda não está em uso nesta "
                "sessão. Feche e abra o FileMorph para habilitá-lo."
            )
        return f"{self.name} encontrado ({details})."


@dataclass(frozen=True)
class DiagnosticReport:
    app_name: str
    app_version: str
    windows: str
    python: str
    packaged: bool
    qt_version: str | None
    data_dir: str
    logs_dir: str
    output_folder: str
    dependencies: tuple[DependencyInfo, ...] = field(default_factory=tuple)

    def as_text(self) -> str:
        """O relatório em texto simples, para colar numa mensagem de suporte."""
        lines = [
            f"{self.app_name} {self.app_version}",
            f"Windows: {self.windows}",
            f"Python: {self.python}" + (" (empacotado)" if self.packaged else " (desenvolvimento)"),
        ]
        if self.qt_version:
            lines.append(f"Qt: {self.qt_version}")
        lines += [
            f"Configurações: {self.data_dir}",
            f"Logs: {self.logs_dir}",
            f"Pasta de saída: {self.output_folder}",
        ]
        for dependency in self.dependencies:
            lines.append("")
            lines.append(dependency.status_text())
            if dependency.path:
                lines.append(f"  Caminho: {dependency.path}")
            if dependency.offered_formats:
                lines.append(f"  Formatos disponíveis: {', '.join(dependency.offered_formats)}")
            if not dependency.available:
                lines.append("  Necessário para: " + "; ".join(dependency.features))
        return "\n".join(lines)


def windows_description() -> str:
    """"Windows 11 (10.0.26200)" — ou a descrição genérica fora do Windows."""
    if sys.platform != "win32":
        return platform.platform()
    build = sys.getwindowsversion().build  # type: ignore[attr-defined]
    release = "11" if build >= 22000 else platform.release()
    edition = platform.win32_edition() if hasattr(platform, "win32_edition") else ""
    name = f"Windows {release}"
    if edition:
        name += f" {edition}"
    return f"{name} ({platform.version()}, {platform.machine()})"


def collect_diagnostics(
    *,
    output_folder: str,
    data_dir: str,
    logs_dir: str,
    ffmpeg_active_formats: Iterable[str] = (),
    libreoffice_active: bool = False,
    qt_version: str | None = None,
    ffmpeg: FFmpegManager | None = None,
    libreoffice: LibreOfficeManager | None = None,
    refresh: bool = True,
) -> DiagnosticReport:
    """Monta o relatório.

    `ffmpeg_active_formats` e `libreoffice_active` dizem o que as conversões
    registradas na abertura do aplicativo oferecem — a janela sabe isso pelo
    registro de compatibilidade. `refresh` refaz a detecção dos programas,
    para encontrar um que tenha sido instalado com o FileMorph aberto.
    """
    ffmpeg = ffmpeg if ffmpeg is not None else ffmpeg_manager
    libreoffice = libreoffice if libreoffice is not None else libreoffice_manager
    ffmpeg_status = ffmpeg.status(force_refresh=refresh)
    office_status = libreoffice.status(force_refresh=refresh)
    offered = tuple(sorted(ext.upper() for ext in ffmpeg_active_formats))

    dependencies = (
        DependencyInfo(
            name="FFmpeg",
            available=ffmpeg_status.available,
            version=ffmpeg_status.version,
            path=ffmpeg_status.executable_path,
            source=ffmpeg_status.source,
            features=FFMPEG_FEATURES,
            download_url=FFMPEG_DOWNLOAD_URL,
            active=ffmpeg_status.available and bool(offered),
            offered_formats=offered,
        ),
        DependencyInfo(
            name="LibreOffice",
            available=office_status.available,
            version=office_status.version,
            path=office_status.executable_path,
            source=None,
            features=LIBREOFFICE_FEATURES,
            download_url=LIBREOFFICE_DOWNLOAD_URL,
            active=office_status.available and libreoffice_active,
        ),
    )
    return DiagnosticReport(
        app_name=APP_NAME,
        app_version=__version__,
        windows=windows_description(),
        python=f"{platform.python_version()} ({platform.architecture()[0]})",
        packaged=bool(getattr(sys, "frozen", False)),
        qt_version=qt_version,
        data_dir=data_dir,
        logs_dir=logs_dir,
        output_folder=output_folder,
        dependencies=dependencies,
    )


def dependency_hint(
    extensions: Iterable[str],
    mode: str,
    *,
    ffmpeg_available: bool,
    libreoffice_available: bool,
) -> str | None:
    """Uma frase explicando o que falta instalar para os arquivos da lista, ou
    None quando nada falta.

    Só fala do que muda alguma coisa para o modo escolhido: sem LibreOffice,
    um DOCX ainda vira TXT, então a frase diz exatamente que é o PDF que
    depende dele.
    """
    extensions = {ext.lower().lstrip(".") for ext in extensions}
    categories = {get_file_category(f"x.{ext}") for ext in extensions}
    office = extensions & {"docx", "xlsx"}

    hints: list[str] = []
    if mode == "convert" and categories & {"audio", "video"} and not ffmpeg_available:
        hints.append(
            "Áudio e vídeo precisam do FFmpeg, que não foi encontrado nesta máquina."
        )
    if office and not libreoffice_available:
        names = " e ".join(sorted(ext.upper() for ext in office))
        if mode == "convert":
            hints.append(f"Para transformar {names} em PDF é preciso instalar o LibreOffice.")
        elif mode == "merge":
            hints.append(f"Para usar {names} no modo Juntar é preciso instalar o LibreOffice.")
    if not hints:
        return None
    return " ".join(hints) + " Veja ⋯ → Diagnóstico."
