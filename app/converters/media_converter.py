"""
Base comum dos conversores que rodam sobre o FFmpeg (FASE 6).

Áudio e vídeo são famílias diferentes para o usuário, mas por dentro a
conversão é o mesmo roteiro: descobrir a duração, montar a linha de
comando, gravar em um arquivo temporário e só então movê-lo para o
nome definitivo. Esse roteiro mora aqui uma vez só; `audio_converter.py`
e `video_converter.py` entram apenas com a lista de formatos que sabem
ler e com o *perfil* de cada formato de saída.

O que um perfil descreve (`MediaProfile`):

- **quais argumentos** o FFmpeg recebe para gravar aquele formato
  (codificador, qualidade, opções de compatibilidade);
- **de quais codificadores** ele depende. Nem toda compilação do FFmpeg
  traz libx264 ou libvpx-vp9 — a do Windows costuma trazer, a de uma
  distribuição enxuta muitas vezes não. Em vez de deixar o usuário
  descobrir isso quando a conversão falha, o conversor pergunta ao
  `FFmpegManager` o que existe nesta máquina e só oferece o que puder
  mesmo cumprir (item 37).

Garantias que valem para todos os conversores de mídia:

- O arquivo de origem nunca é modificado nem apagado (item 18): o
  FFmpeg só o abre para leitura.
- A gravação é atômica: a saída vai para um temporário ao lado do
  destino e só depois é movida para o nome final. Uma falha (ou um
  cancelamento) no meio da conversão nunca deixa um arquivo truncado,
  nem destrói um arquivo bom que já ocupasse aquele nome.
- Nenhuma exceção escapa para a interface: qualquer erro vira um
  `ConversionResult(success=False)` com mensagem em português, e o
  relatório técnico do FFmpeg vai para o log (itens 22 e 23).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.converter import BaseConverter, ConversionResult
from app.core.task_context import NULL_CONTEXT, OperationCancelled, TaskContext
from app.utils.ffmpeg_manager import FFmpegError, FFmpegManager, ffmpeg_manager
from app.utils.file_utils import (
    ensure_directory,
    get_extension,
    get_filename,
    temp_output_path,
)
from app.utils.logger import get_logger

logger = get_logger("converters.media")


@dataclass(frozen=True)
class MediaProfile:
    """Como gravar um formato de destino.

    `arguments` são as opções passadas ao FFmpeg antes do arquivo de
    saída; `requires` são os codificadores que precisam existir nesta
    instalação para que essas opções funcionem.
    """

    arguments: tuple[str, ...]
    requires: tuple[str, ...] = field(default_factory=tuple)


class MediaConverter(BaseConverter):
    """Esqueleto de um conversor baseado em FFmpeg.

    As subclasses declaram `sources` (extensões que sabem ler),
    `profiles` (um `MediaProfile` por extensão de saída) e, se
    precisarem, `common_arguments` — opções que valem para todos os
    destinos daquele conversor.
    """

    #: Extensões de entrada aceitas por este conversor.
    sources: set[str] = set()

    #: Um perfil de gravação por extensão de saída.
    profiles: dict[str, MediaProfile] = {}

    #: Opções aplicadas a qualquer destino deste conversor.
    common_arguments: tuple[str, ...] = ()

    #: Nome do que este conversor produz, usado nas mensagens de erro.
    produces: str = "arquivo"

    def __init__(self, manager: FFmpegManager | None = None) -> None:
        # O gerenciador é injetável para que os testes possam usar um
        # FFmpeg de mentira e exercitar progresso, erro e cancelamento
        # sem depender do binário estar instalado na máquina.
        self._manager = manager or ffmpeg_manager

    # --- Camada de compatibilidade ---------------------------------------

    @property
    def source_formats(self) -> set[str]:
        return set(self.sources)

    @property
    def target_formats(self) -> set[str]:
        """Só os formatos cujos codificadores existem nesta instalação.

        O `FFmpegManager` guarda a lista de codificadores depois da
        primeira consulta, então esta propriedade — chamada a cada
        pergunta do seletor de formato — não custa um processo externo.
        """
        encoders = self._manager.available_encoders()
        return {
            extension
            for extension, profile in self.profiles.items()
            if all(encoder in encoders for encoder in profile.requires)
        }

    # --- Conversão --------------------------------------------------------

    def convert(
        self, input_path: str, output_path: str, context: TaskContext | None = None
    ) -> ConversionResult:
        context = context or NULL_CONTEXT
        source = Path(input_path)
        destination = Path(output_path)
        target_ext = get_extension(destination)
        started_at = time.monotonic()

        profile = self.profiles.get(target_ext)
        if profile is None:
            return self._failure(
                input_path,
                f"O FileMorph ainda não sabe gerar {self.produces} em .{target_ext}.",
            )
        if not self._manager.is_available():
            # Rede de segurança: sem FFmpeg o conversor nem chega a ser
            # registrado, então este caminho só existe para o caso de
            # alguém chamá-lo diretamente.
            return self._failure(
                input_path,
                "A conversão de áudio e vídeo depende do FFmpeg, que não foi "
                "encontrado nesta máquina. Instale-o e adicione a pasta 'bin' "
                "ao PATH do Windows.",
            )
        missing = [e for e in profile.requires if not self._manager.has_encoder(e)]
        if missing:
            return self._failure(
                input_path,
                f"Esta instalação do FFmpeg não tem o codificador "
                f"'{missing[0]}', necessário para gravar .{target_ext}.",
            )
        if not source.is_file():
            return self._failure(
                input_path, f"O arquivo '{get_filename(source)}' não foi encontrado."
            )

        temp_output: Path | None = None
        try:
            context.check_cancelled()
            ensure_directory(destination.parent)
            # O FFmpeg deduz o formato de saída pela extensão, então o
            # temporário precisa terminar com a extensão do destino.
            temp_output = temp_output_path(destination, keep_extension=True)

            self._manager.run(
                [
                    "-i",
                    str(source),
                    *self.common_arguments,
                    *profile.arguments,
                    str(temp_output),
                ],
                context=context,
                total_seconds=self._manager.probe_duration(source),
            )

            temp_output.replace(destination)
            temp_output = None
        except OperationCancelled:
            raise  # não é falha: quem trata é a fila
        except FFmpegError as exc:
            # A mensagem já vem traduzida pelo gerenciador.
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
                "Erro inesperado ao converter este arquivo. Veja os logs para detalhes.",
            )
        finally:
            # Vale para os três desfechos: sucesso (aqui já é None),
            # falha e cancelamento. É isto que garante que uma conversão
            # interrompida não deixe sobras na pasta do usuário.
            if temp_output is not None:
                temp_output.unlink(missing_ok=True)

        context.report(100)
        logger.info(
            "Conversão concluída | FFmpeg | %s -> %s | %.2fs",
            get_filename(source),
            get_filename(destination),
            time.monotonic() - started_at,
        )
        return ConversionResult(
            success=True, input_path=input_path, output_path=str(destination)
        )

    @staticmethod
    def _failure(input_path: str, message: str) -> ConversionResult:
        logger.warning("Conversão falhou | %s | %s", get_filename(input_path), message)
        return ConversionResult(
            success=False, input_path=input_path, error_message=message
        )
