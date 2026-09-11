"""
Janela principal do FileMorph (item 5 do briefing).

Layout: barra de modo (Converter / Juntar), área de drop, lista de
arquivos, seletor de formato (modo Converter) e botão principal —
compacto, único, sem múltiplas janelas para o fluxo básico.

Esta janela NUNCA fala diretamente com Pillow/pypdf/FFmpeg. Ela passa
tudo por `FileProcessor` (app/core/processor.py), que por sua vez só
executa o que a camada de compatibilidade confirma como implementado.
Para as combinações ainda sem conversor (documentos, planilhas) — e
para áudio e vídeo em uma máquina sem FFmpeg —, o botão principal
continua desabilitado com uma mensagem honesta, em vez de simular um
processamento que não existe (item 37).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config.settings import settings_manager
from app.core.converter import compatibility_registry
from app.core.processor import BatchRequest, FileProcessor
from app.core.task_queue import TaskQueue
from app.ui.file_drop_area import FileDropArea
from app.ui.file_list import FileListWidget, FileStatus
from app.ui.format_selector import FormatSelector
from app.ui.mascot import MascotState, duration_of
from app.ui.progress_widget import ProgressWidget
from app.ui.settings_window import SettingsWindow
from app.ui.styles import build_stylesheet, get_palette, resolve_theme_name
from app.utils.ffmpeg_manager import ffmpeg_manager
from app.utils.libreoffice_manager import libreoffice_manager
from app.utils.file_utils import (
    ensure_directory,
    get_extension,
    get_filename,
    get_stem,
    resolve_output_path,
)
from app.utils.logger import get_logger, get_logs_dir
from app.utils.resources import ICON_PATH, get_asset

logger = get_logger("ui.main_window")

# Cada momento do aplicativo tem uma fala e uma reação do mascote, e as
# duas ficam na mesma tabela para não poderem divergir: acrescentar um
# momento aqui obriga a decidir as duas coisas de uma vez. Antes da
# Fase 8 esta tabela só tinha o texto, e a figura era uma imagem parada.
_MASCOT_MOMENTS: dict[str, tuple[str, MascotState]] = {
    "idle": ("Jogue seus arquivos aqui! 📥", MascotState.IDLE),
    "files_added": ("Boa! Agora escolha o que fazer com eles.", MascotState.READY),
    "processing": ("Só um segundo...", MascotState.WORKING),
    "done": ("Prontinho! ✨", MascotState.HAPPY),
    "partial": ("Terminei, mas alguns arquivos deram problema.", MascotState.SAD),
    "error": ("Ops! Esse arquivo deu problema.", MascotState.SAD),
    "cancelled": ("Tudo bem, parei por aqui.", MascotState.CANCELLED),
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FileMorph")
        self.setMinimumSize(480, 640)

        # O mesmo ícone que o atalho do Windows usa, agora na barra de
        # tarefas e no canto da janela. Ausente, o Qt cai no ícone padrão.
        icone = get_asset(*ICON_PATH)
        if icone is not None:
            self.setWindowIcon(QIcon(str(icone)))

        self._task_queue = TaskQueue(max_concurrent=settings_manager.settings.max_concurrent_tasks)
        self._processor = FileProcessor(self._task_queue)
        self._mode = "convert"  # "convert" | "merge"

        # Estado do lote em andamento. `_batch_total == 0` significa que
        # não há processamento ativo — é o que impede que sinais tardios
        # da fila abram diálogos fora de hora.
        self._batch_total = 0
        self._batch_succeeded: list[str] = []
        self._batch_failed: list[tuple[str, str]] = []
        self._batch_stopped: list[str] = []
        # Andamento das tarefas ainda em curso, por id (0-100). É o que
        # faz a barra avançar dentro de um arquivo grande, e não só
        # quando ele termina (Fase 5).
        self._task_progress: dict[str, int] = {}
        # A barra é calculada em tarefas, não em arquivos: converter 3
        # arquivos são 3 tarefas, mas juntar 3 arquivos é uma só.
        self._batch_units = 0
        self._tasks_finished = 0
        self._batch_cancelled = False
        self._batch_output_dir = ""
        # Preenchido só no modo Juntar: o lote inteiro produz este único
        # arquivo, e o resumo final precisa falar dele, não de "N arquivos".
        self._batch_merge_output: str | None = None

        self._task_queue.task_started.connect(self._on_task_started)
        self._task_queue.task_finished.connect(self._on_task_finished)
        self._task_queue.task_failed.connect(self._on_task_failed)
        self._task_queue.task_cancelled.connect(self._on_task_cancelled)
        self._task_queue.task_progress.connect(self._on_task_progress)
        self._task_queue.all_tasks_finished.connect(self._on_batch_finished)

        self._build_ui()
        self._build_menu()
        self._apply_theme()
        self._apply_mascot_settings()
        self._say("idle")
        self._check_dependencies_async()

    # --- Construção da UI ------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(14)

        # Cabeçalho com título e alternância de modo
        header = QHBoxLayout()
        title = QLabel("◉ FileMorph")
        title.setObjectName("titleLabel")
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        mode_row = QHBoxLayout()
        mode_row.addStretch()
        self._convert_button = QPushButton("CONVERTER")
        self._merge_button = QPushButton("JUNTAR")
        for btn in (self._convert_button, self._merge_button):
            btn.setObjectName("modeButton")
            btn.setCheckable(True)
        self._convert_button.setChecked(True)

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._convert_button)
        self._mode_group.addButton(self._merge_button)
        self._mode_group.buttonClicked.connect(self._on_mode_changed)

        mode_row.addWidget(self._convert_button)
        mode_row.addWidget(self._merge_button)
        mode_row.addStretch()
        root.addLayout(mode_row)

        # Área de drop
        self._drop_area = FileDropArea()
        self._drop_area.files_dropped.connect(self._on_files_dropped)
        root.addWidget(self._drop_area)

        # A fala do mascote. A figura dele mora dentro da area de
        # arrastar (ver app/ui/file_drop_area.py), que e onde ela recebe
        # quem chega - repeti-la aqui seria mostrar o mesmo desenho duas
        # vezes na mesma tela.
        self._mascot_label = QLabel()
        self._mascot_label.setObjectName("mascotLabel")
        self._mascot_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self._mascot_label)

        # Lista de arquivos
        list_title = QLabel("Arquivos adicionados")
        list_title.setObjectName("hintLabel")
        root.addWidget(list_title)

        self._file_list = FileListWidget()
        self._file_list.files_changed.connect(self._on_files_changed)
        root.addWidget(self._file_list, 1)

        # Seletor de formato (modo Converter)
        format_row = QHBoxLayout()
        self._format_label = QLabel("Converter para:")
        self._format_selector = FormatSelector()
        self._format_selector.format_selected.connect(lambda _ext: self._update_primary_button())
        format_row.addWidget(self._format_label)
        format_row.addWidget(self._format_selector, 1)
        root.addLayout(format_row)
        self._format_row_widget = format_row

        # Widget de progresso
        self._progress_widget = ProgressWidget()
        self._progress_widget.cancel_requested.connect(self._on_cancel_requested)
        root.addWidget(self._progress_widget)

        # Botão principal
        self._primary_button = QPushButton("CONVERTER ARQUIVOS")
        self._primary_button.setObjectName("primaryButton")
        self._primary_button.clicked.connect(self._on_primary_clicked)
        root.addWidget(self._primary_button)

        self._update_primary_button()

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("Menu")

        settings_action = menu.addAction("Configurações")
        settings_action.triggered.connect(self._open_settings)

        deps_action = menu.addAction("Verificar dependências")
        deps_action.triggered.connect(self._check_dependencies_dialog)

        logs_action = menu.addAction("Abrir pasta de logs")
        logs_action.triggered.connect(self._open_logs_folder)

        menu.addSeparator()

        help_action = menu.addAction("Ajuda")
        help_action.triggered.connect(self._show_help)

        about_action = menu.addAction("Sobre")
        about_action.triggered.connect(self._show_about)

    def _apply_theme(self) -> None:
        theme_name = resolve_theme_name(settings_manager.settings.theme)
        palette = get_palette(theme_name)
        self.setStyleSheet(build_stylesheet(palette))

    # --- Mascote -----------------------------------------------------------

    def _say(self, moment: str) -> None:
        """Faz o mascote falar e reagir ao que acabou de acontecer.

        Uma reação (comemorar, levar um susto) termina e devolve o
        mascote ao estado de repouso. Qual é esse repouso depende da
        lista de arquivos *agora* — não do que estava acontecendo antes
        —, e é por isso que ele é reafirmado antes da reação: sem isso,
        depois de comemorar o fim de uma conversão o mascote voltaria a
        se mexer como se ainda estivesse trabalhando.
        """
        text, state = _MASCOT_MOMENTS[moment]
        self._mascot_label.setText(text)
        if duration_of(state) is not None:
            self._drop_area.set_mascot_state(self._resting_state())
        self._drop_area.set_mascot_state(state)

    def _resting_state(self) -> MascotState:
        return MascotState.IDLE if self._file_list.is_empty() else MascotState.READY

    def _apply_mascot_settings(self) -> None:
        """Aplica as duas opções do mascote — a fala e o movimento.

        As duas existiam nas configurações desde a Fase 1 sem fazer
        efeito nenhum, o que contraria o princípio do projeto de não ter
        controle decorativo. A Fase 8 as ligou de verdade.
        """
        settings = settings_manager.settings
        self._mascot_label.setVisible(settings.show_mascot_messages)
        self._drop_area.set_mascot_animated(settings.animations_enabled)

    # --- Eventos de arquivos ---------------------------------------------

    def _on_files_dropped(self, valid: list[str], invalid: list[str]) -> None:
        added = self._file_list.add_files(valid)
        if added:
            self._say("files_added")
        if invalid:
            names = "\n".join(invalid[:10])
            more = "" if len(invalid) <= 10 else f"\n... e mais {len(invalid) - 10} arquivo(s)"
            QMessageBox.warning(
                self,
                "Arquivos não suportados",
                f"Os arquivos abaixo não são suportados pelo FileMorph e não foram adicionados:\n\n{names}{more}",
            )

    def _on_files_changed(self) -> None:
        source_exts = [get_extension(p) for p in self._file_list.get_paths()]
        self._format_selector.refresh(source_exts)
        self._update_primary_button()
        if self._file_list.is_empty():
            self._say("idle")

    def _on_mode_changed(self) -> None:
        self._mode = "convert" if self._convert_button.isChecked() else "merge"
        is_convert = self._mode == "convert"
        # No modo Juntar não há formato a escolher: a junção desta versão
        # sempre produz um PDF, e o nome do arquivo é pedido na hora.
        self._format_selector.setVisible(is_convert)
        self._format_label.setVisible(is_convert)
        self._primary_button.setText("CONVERTER ARQUIVOS" if is_convert else "JUNTAR ARQUIVOS")
        self._update_primary_button()

    # --- Botão principal ---------------------------------------------------

    def _update_primary_button(self) -> None:
        if self._batch_total:
            # Há um lote em andamento: o caminho para interromper é o
            # botão "Cancelar" do progresso, não um segundo clique aqui.
            self._primary_button.setEnabled(False)
            self._primary_button.setToolTip("Processando...")
            return

        paths = self._file_list.get_paths()
        if not paths:
            self._primary_button.setEnabled(False)
            self._primary_button.setToolTip("Adicione arquivos para começar.")
            return

        if self._mode == "convert":
            can_run = self._format_selector.has_valid_selection() and self._processor.can_convert_batch(
                paths, self._format_selector.current_extension() or ""
            )
            tooltip = "" if can_run else "Ainda não há conversão disponível para estes arquivos nesta versão."
        else:
            can_run = len(paths) >= 2 and self._processor.can_merge(paths)
            tooltip = "" if can_run else "Ainda não há junção disponível para estes arquivos nesta versão."

        self._primary_button.setEnabled(can_run)
        self._primary_button.setToolTip(tooltip)

    def _on_primary_clicked(self) -> None:
        if self._batch_total:  # já há um lote rodando
            return

        paths = self._file_list.get_paths()
        if not paths:
            return
        output_dir = settings_manager.settings.output_folder

        if self._mode == "convert":
            target_ext = self._format_selector.current_extension()
            if not target_ext:
                return

            policy = self._resolve_overwrite_policy(paths, target_ext, output_dir)
            if policy is None:  # usuário cancelou no diálogo de conflito
                return

            self._start_batch(paths, output_dir)
            self._processor.convert_batch(
                BatchRequest(
                    input_paths=paths,
                    target_extension=target_ext,
                    output_dir=output_dir,
                    overwrite_policy=policy,
                )
            )
        else:
            output_path = self._ask_merge_destination(output_dir)
            if output_path is None:  # usuário fechou o diálogo
                return
            self._start_batch(paths, str(Path(output_path).parent), units=1)
            self._batch_merge_output = output_path
            self._processor.merge_files(paths, output_path)

    def _ask_merge_destination(self, output_dir: str) -> str | None:
        """Pergunta onde salvar o arquivo final da junção.

        O próprio diálogo do sistema já cuida de confirmar a
        substituição de um arquivo existente, então aqui não há um
        segundo fluxo de conflito.
        """
        suggested = ensure_directory(output_dir) / "documento_final.pdf"
        chosen, _filter = QFileDialog.getSaveFileName(
            self, "Salvar arquivo final", str(suggested), "PDF (*.pdf)"
        )
        if not chosen:
            return None
        # Em diálogos não nativos a extensão pode não vir junto do nome.
        if get_extension(chosen) != "pdf":
            chosen = f"{chosen}.pdf"
        return chosen

    def _resolve_overwrite_policy(
        self, paths: list[str], target_ext: str, output_dir: str
    ) -> str | None:
        """Pergunta ao usuário o que fazer quando o arquivo de destino já
        existe (item 21). Retorna 'replace', 'copy' ou None (cancelar).

        Um destino que é o próprio arquivo de origem não conta como
        conflito: o `FileProcessor` sempre gera uma cópia nesse caso,
        justamente para nunca destruir o original.
        """
        conflicts: list[str] = []
        for path in paths:
            candidate = resolve_output_path(output_dir, get_stem(path), target_ext)
            if not candidate.exists():
                continue
            if candidate.resolve() == Path(path).resolve():
                continue
            conflicts.append(candidate.name)

        if not conflicts:
            return "replace"
        if not settings_manager.settings.ask_before_overwrite:
            return "replace"

        listed = "\n".join(conflicts[:8])
        if len(conflicts) > 8:
            listed += f"\n... e mais {len(conflicts) - 8} arquivo(s)"

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Arquivo já existe")
        box.setText(
            f"{len(conflicts)} arquivo(s) com esse nome já existem na pasta de destino."
        )
        box.setInformativeText(f"{listed}\n\nO que você quer fazer?")
        replace_button = box.addButton("Substituir", QMessageBox.ButtonRole.DestructiveRole)
        copy_button = box.addButton("Criar cópia", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(copy_button)
        box.exec()

        clicked = box.clickedButton()
        if clicked is replace_button:
            return "replace"
        if clicked is copy_button:
            return "copy"
        return None

    def _start_batch(self, paths: list[str], output_dir: str, units: int | None = None) -> None:
        """Prepara a interface para um lote. `units` é o número de tarefas
        que a fila vai executar, que só coincide com o número de arquivos
        no modo Converter."""
        self._batch_total = len(paths)
        self._batch_units = max(1, units if units is not None else len(paths))
        self._tasks_finished = 0
        self._batch_merge_output = None
        self._batch_succeeded = []
        self._batch_failed = []
        self._batch_stopped = []
        self._task_progress = {}
        self._batch_cancelled = False
        self._batch_output_dir = output_dir

        for path in paths:
            self._file_list.set_status(path, FileStatus.WAITING)

        self._primary_button.setEnabled(False)
        self._say("processing")
        self._progress_widget.start(self._batch_total)

    def _on_cancel_requested(self) -> None:
        if not self._batch_total:
            return
        self._batch_cancelled = True
        self._task_queue.cancel_all()

    # --- Retorno da fila de tarefas ----------------------------------------

    def _on_task_started(self, task_id: str) -> None:
        path = self._path_from_task_id(task_id)
        if path and path in self._file_list.get_paths():
            self._file_list.set_status(path, FileStatus.PROCESSING)
            self._progress_widget.update_current_file(get_filename(path))
        elif self._batch_merge_output:
            # A junção é uma tarefa só, sobre vários arquivos: o que faz
            # sentido mostrar é o documento que está sendo montado.
            self._progress_widget.update_current_file(get_filename(self._batch_merge_output))
            for merged_path in self._file_list.get_paths():
                self._file_list.set_status(merged_path, FileStatus.PROCESSING)

    def _on_task_finished(self, task_id: str, result: object) -> None:
        if not self._batch_total:
            return

        success = bool(getattr(result, "success", False))
        message = getattr(result, "error_message", None) or "Não foi possível concluir."
        # Conversão devolve um arquivo de entrada; junção devolve vários.
        affected = getattr(result, "input_paths", None) or [
            getattr(result, "input_path", None) or self._path_from_task_id(task_id)
        ]

        self._task_progress.pop(task_id, None)
        self._tasks_finished += 1
        for path in affected:
            if not path:
                continue
            if success:
                self._batch_succeeded.append(path)
                self._file_list.set_status(path, FileStatus.DONE)
            else:
                self._batch_failed.append((path, message))
                self._file_list.set_status(path, FileStatus.ERROR, message)

        self._report_batch_progress()

    def _on_task_failed(self, task_id: str, message: str) -> None:
        """Só chega aqui quando a tarefa levantou exceção — os conversores
        capturam os próprios erros e respondem por `task_finished`. É a
        rede de segurança para que a interface nunca fique travada."""
        if not self._batch_total:
            return
        self._task_progress.pop(task_id, None)
        self._tasks_finished += 1
        path = self._path_from_task_id(task_id)
        if path:
            self._batch_failed.append((path, message))
            self._file_list.set_status(path, FileStatus.ERROR, message)
        self._report_batch_progress()

    def _on_task_cancelled(self, task_id: str) -> None:
        """Tarefa que não chegou a rodar, ou que parou no meio quando o
        usuário mandou. Não é erro: o arquivo volta a aparecer como
        pendente de conversão, sem mensagem de falha (item 17)."""
        if not self._batch_total:
            return
        self._task_progress.pop(task_id, None)
        self._tasks_finished += 1
        path = self._path_from_task_id(task_id)
        if path:
            self._batch_stopped.append(path)
            self._file_list.set_status(path, FileStatus.CANCELLED)
        self._report_batch_progress()

    def _on_task_progress(self, task_id: str, percent: int) -> None:
        """Andamento vindo de dentro de uma tarefa (página 12 de 40)."""
        if not self._batch_total:
            return
        self._task_progress[task_id] = percent
        self._report_batch_progress()

    def _report_batch_progress(self) -> None:
        """Combina os arquivos já finalizados com o andamento parcial dos
        que ainda estão rodando, para a barra avançar de forma contínua
        mesmo num lote de poucos arquivos grandes."""
        files_done = len(self._batch_succeeded) + len(self._batch_failed) + len(self._batch_stopped)
        in_flight = sum(self._task_progress.values())
        percent = round((self._tasks_finished * 100 + in_flight) / self._batch_units)
        self._progress_widget.report(min(files_done, self._batch_total), percent)

    def _on_batch_finished(self) -> None:
        if not self._batch_total:
            return

        succeeded = len(self._batch_succeeded)
        stopped = len(self._batch_stopped)
        failed = list(self._batch_failed)
        output_dir = self._batch_output_dir
        merge_output = self._batch_merge_output
        cancelled = self._batch_cancelled

        self._batch_total = 0
        self._progress_widget.finish()
        self._update_primary_button()

        if cancelled:
            self._say("cancelled")
            QMessageBox.information(
                self,
                "Operação cancelada",
                f"Operação interrompida. {succeeded} arquivo(s) já tinham sido "
                f"concluídos; {stopped} não chegaram a ser processados.",
            )
            return

        if failed:
            self._say("partial" if succeeded else "error")
            details = "\n".join(f"• {get_filename(p)}: {msg}" for p, msg in failed[:8])
            if len(failed) > 8:
                details += f"\n... e mais {len(failed) - 8} arquivo(s)"
            QMessageBox.warning(
                self,
                "Concluído com erros",
                f"{succeeded} arquivo(s) concluído(s), {len(failed)} com erro:\n\n{details}",
            )
        else:
            self._say("done")
            if merge_output:
                summary = f"{succeeded} arquivo(s) unido(s) em:\n{merge_output}"
            else:
                summary = f"{succeeded} arquivo(s) salvo(s) em:\n{output_dir}"
            QMessageBox.information(self, "Tudo pronto", summary)

        if succeeded and settings_manager.settings.open_folder_after_finish:
            QDesktopServices.openUrl(QUrl.fromLocalFile(output_dir))

    @staticmethod
    def _path_from_task_id(task_id: str) -> str | None:
        """Os ids gerados pelo processador têm a forma 'convert:<caminho>'
        ou 'merge:<caminho de saída>'. Só o primeiro aponta para um
        arquivo da lista."""
        prefix, separator, remainder = task_id.partition(":")
        if separator and prefix == "convert":
            return remainder
        return None

    # --- Dependências ------------------------------------------------------

    def _check_dependencies_async(self) -> None:
        # Verificação leve o suficiente para não precisar de thread própria
        # aqui; caso vire uma operação mais pesada no futuro, deve passar
        # a rodar via TaskQueue para não travar a abertura da janela.
        if not ffmpeg_manager.status().available:
            logger.info("FFmpeg não encontrado — conversões de áudio/vídeo ficarão indisponíveis.")
        if not libreoffice_manager.status().available:
            logger.info("LibreOffice não encontrado — DOCX para PDF ficará indisponível.")

    def _check_dependencies_dialog(self) -> None:
        """Relata o estado real dos dois programas externos do projeto.

        Um aviso vale para os dois: os conversores são registrados uma
        única vez, na inicialização (ver `main.py`). Se o usuário instalar
        o FFmpeg ou o LibreOffice com o FileMorph aberto, esta janela vai
        encontrá-lo, mas o seletor de formato só vai oferecer as novas
        conversões depois de reiniciar — e é isso que a mensagem precisa
        dizer, em vez de deixar o usuário achando que está tudo pronto.
        """
        message = self._ffmpeg_report() + "\n\n" + self._libreoffice_report()
        QMessageBox.information(self, "Dependências", message)

    def _ffmpeg_report(self) -> str:
        status = ffmpeg_manager.status(force_refresh=True)

        if not status.available:
            return (
                "✗ FFmpeg não encontrado no sistema.\n"
                "Sem ele, áudio e vídeo não aparecem no seletor de formato. "
                "Para habilitá-los, baixe o FFmpeg em ffmpeg.org, descompacte "
                "e adicione a pasta 'bin' ao PATH do Windows."
            )

        version = status.version or "desconhecida"
        audio_targets = compatibility_registry.available_targets_for("mp3")
        video_targets = compatibility_registry.available_targets_for("mp4")

        if not audio_targets and not video_targets:
            return (
                f"✓ FFmpeg encontrado (versão {version}), mas ele ainda não "
                "está em uso nesta sessão.\n"
                "Feche e abra o FileMorph para habilitar as conversões de "
                "áudio e vídeo."
            )

        report = f"✓ FFmpeg encontrado (versão {version}).\n"
        if audio_targets:
            report += (
                "De um arquivo de áudio você pode gerar: "
                f"{self._format_list(audio_targets)}.\n"
            )
        if video_targets:
            report += f"De um vídeo você pode gerar: {self._format_list(video_targets)}.\n"
        return report + (
            "Os formatos oferecidos dependem dos codificadores desta "
            "instalação do FFmpeg — o que não aparece aqui é o que esta "
            "compilação não sabe gravar."
        )

    def _libreoffice_report(self) -> str:
        status = libreoffice_manager.status(force_refresh=True)

        if not status.available:
            return (
                "✗ LibreOffice não encontrado no sistema.\n"
                "Ele é necessário apenas para converter DOCX em PDF, que é a "
                "conversão que precisa paginar o documento. As demais "
                "conversões de documento (DOCX em TXT, TXT em DOCX, TXT em PDF "
                "e PDF em TXT) funcionam sem ele.\n"
                "Para habilitá-la, instale o LibreOffice (libreoffice.org)."
            )

        version = status.version or "desconhecida"
        if not compatibility_registry.can_convert("docx", "pdf"):
            return (
                f"✓ LibreOffice encontrado (versão {version}), mas ele ainda "
                "não está em uso nesta sessão.\n"
                "Feche e abra o FileMorph para habilitar a conversão de DOCX "
                "em PDF."
            )
        return (
            f"✓ LibreOffice encontrado (versão {version}).\n"
            "Um DOCX pode virar PDF com o layout preservado, e também entra no "
            "modo Juntar."
        )

    @staticmethod
    def _format_list(extensions: set[str]) -> str:
        return ", ".join(ext.upper() for ext in sorted(extensions))

    # --- Menu ---------------------------------------------------------------

    def _open_settings(self) -> None:
        dialog = SettingsWindow(settings_manager, parent=self)
        if dialog.exec():
            self._task_queue.set_max_concurrent(settings_manager.settings.max_concurrent_tasks)
            self._apply_theme()
            self._apply_mascot_settings()

    def _open_logs_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(get_logs_dir())))

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "Ajuda",
            "Arraste seus arquivos para a área central, escolha o formato de "
            "destino (ou o modo Juntar) e clique no botão principal.\n\n"
            "Esta versão converte imagens entre PNG, JPG e WEBP, transforma "
            "imagens em PDF e PDF em imagens, converte áudio entre MP3, WAV, "
            "FLAC, OGG e M4A, converte vídeo entre MP4, MKV e WEBM, extrai a "
            "trilha sonora de um vídeo como arquivo de áudio e converte "
            "documentos entre DOCX, TXT e PDF. Os arquivos convertidos são "
            "salvos na pasta definida em Configurações, e o original nunca é "
            "alterado.\n\n"
            "No modo Juntar, vários PDFs, imagens e documentos viram um único "
            "PDF, na ordem em que aparecem na lista.\n\n"
            "Ir para TXT guarda só o texto: negrito, imagens e layout não "
            "couberam em um arquivo de texto, e isso vale para qualquer "
            "programa. Um PDF digitalizado também não tem texto por dentro — é "
            "a imagem de uma página —, e o FileMorph não faz reconhecimento de "
            "texto.\n\n"
            "Áudio e vídeo dependem do FFmpeg instalado no sistema, e DOCX → "
            "PDF depende do LibreOffice: use 'Verificar dependências' no menu "
            "para ver o que está habilitado nesta máquina. Converter vídeo é "
            "demorado — leva na ordem da duração do próprio vídeo —, e o botão "
            "Cancelar interrompe a conversão em andamento a qualquer momento.",
        )

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "Sobre o FileMorph",
            "FileMorph — converta, transforme e junte arquivos localmente.\n\n"
            "Versão em desenvolvimento (Fase 8: imagens PNG/JPG/WEBP, PDF, "
            "junção em PDF, áudio MP3/WAV/FLAC/OGG/M4A e vídeo MP4/MKV/WEBM "
            "via FFmpeg, documentos DOCX/TXT/PDF e o mascote animado).",
        )
