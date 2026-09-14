"""
Janela principal do FileMorph.

Layout: barra de modo (Converter / Juntar / Organizar), área de drop,
lista de arquivos, seletor de formato (modo Converter) e botão principal
— compacto, único, sem múltiplas janelas para o fluxo básico. A exceção
é o modo Organizar, que abre uma janela própria para mostrar as páginas
do PDF (ver app/ui/page_organizer_dialog.py).

Esta janela NUNCA fala diretamente com Pillow/pypdf/FFmpeg. Ela passa
tudo por `FileProcessor` (app/core/processor.py), que por sua vez só
executa o que a camada de compatibilidade confirma como implementado.
Para as combinações sem conversor — e para áudio e vídeo numa máquina
sem FFmpeg —, o botão principal fica desabilitado com uma mensagem
honesta, em vez de simular um processamento que não existe.

O acompanhamento de um lote em andamento — que tarefa cuida de quais
arquivos, o progresso, o cancelamento, o resumo final — mora no
`BatchController` (app/ui/batch_controller.py). Esta janela só começa o
lote e mostra o que ele avisa.
"""

from __future__ import annotations

from pathlib import Path

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config.settings import get_app_data_dir, settings_manager
from app.core.batch import CONVERT, MERGE, ORGANIZE, BatchSummary, FileUpdate
from app.core.diagnostics import collect_diagnostics, dependency_hint
from app.core.merger import input_conflict_message
from app.core.processor import BatchRequest, FileProcessor
from app.core.task_queue import TaskQueue
from app.ui.batch_controller import BatchController
from app.ui.diagnostics_dialog import DiagnosticsDialog
from app.ui.file_drop_area import FileDropArea
from app.ui.file_list import ElidedLabel, FileListWidget
from app.ui.format_selector import FormatSelector
from app.ui.mascot import MascotState, duration_of
from app.ui.page_organizer_dialog import PageOrganizerDialog
from app.ui.progress_widget import ProgressWidget
from app.ui.settings_window import SettingsWindow
from app.ui.styles import (
    Palette,
    build_stylesheet,
    get_palette,
    resolve_theme_name,
    shadow_color,
)
from app.utils.ffmpeg_manager import ffmpeg_manager
from app.utils.file_utils import ensure_directory, get_extension, get_filename
from app.utils.libreoffice_manager import libreoffice_manager
from app.utils.logger import get_logger, get_logs_dir
from app.utils.resources import ICON_PATH, get_asset
from app.version import APP_NAME, APP_URL, __version__

logger = get_logger("ui.main_window")

# Cada momento do aplicativo tem uma fala e uma reação do mascote, e as
# duas ficam na mesma tabela para não poderem divergir: acrescentar um
# momento aqui obriga a decidir as duas coisas de uma vez.
_MASCOT_MOMENTS: dict[str, tuple[str, MascotState]] = {
    "idle": ("Jogue seus arquivos aqui! 📥", MascotState.IDLE),
    "files_added": ("Boa! Agora escolha o que fazer com eles.", MascotState.READY),
    "processing": ("Só um segundo...", MascotState.WORKING),
    "done": ("Prontinho! ✨", MascotState.HAPPY),
    "partial": ("Terminei, mas alguns arquivos deram problema.", MascotState.SAD),
    "error": ("Ops! Esse arquivo deu problema.", MascotState.SAD),
    "cancelled": ("Tudo bem, parei por aqui.", MascotState.CANCELLED),
}

# O texto do botão principal em cada modo.
_PRIMARY_LABELS: dict[str, str] = {
    CONVERT: "CONVERTER ARQUIVOS",
    MERGE: "JUNTAR ARQUIVOS",
    ORGANIZE: "ORGANIZAR PÁGINAS",
}


class MainWindow(QMainWindow):
    def __init__(
        self, processor: FileProcessor | None = None, task_queue: TaskQueue | None = None
    ) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(480, 560)
        self._abrir_no_tamanho_da_tela(560, 720)

        # O mesmo ícone que o atalho do Windows usa, agora na barra de
        # tarefas e no canto da janela. Ausente, o Qt cai no ícone padrão.
        icone = get_asset(*ICON_PATH)
        if icone is not None:
            self.setWindowIcon(QIcon(str(icone)))

        self._task_queue = task_queue or TaskQueue(
            max_concurrent=settings_manager.settings.max_concurrent_tasks
        )
        self._processor = processor or FileProcessor(self._task_queue)
        self._batch = BatchController(self._task_queue, self._processor, self)
        self._batch.batch_started.connect(self._on_batch_started)
        self._batch.file_updated.connect(self._on_file_updated)
        self._batch.progress_changed.connect(self._on_progress_changed)
        self._batch.current_file_changed.connect(self._progress_widget_current_file)
        self._batch.batch_finished.connect(self._on_batch_finished)

        self._mode = CONVERT  # CONVERT | MERGE | ORGANIZE
        # Criada em `_apply_theme`, que roda depois de `_build_ui`: o
        # cálculo do botão principal acontece antes de ela existir.
        self._primary_shadow: QGraphicsDropShadowEffect | None = None

        self._build_ui()
        self._apply_theme()
        self._apply_mascot_settings()
        self._say("idle")
        self._log_dependencies()

    def _abrir_no_tamanho_da_tela(self, largura: int, altura: int) -> None:
        """Abre a janela no tamanho pedido, ou no que couber na tela.

        O tamanho pedido é o confortável: largo o bastante para o nome
        de um arquivo caber inteiro, alto o bastante para a lista
        mostrar alguns cards antes de rolar. Mas ele é um desejo, não
        uma imposição — em uma tela de 768 px de altura, com a barra de
        tarefas comendo o resto, uma janela de 740 nasce com o botão
        principal embaixo da barra, e o usuário precisa mover a janela
        para conseguir clicar no que o aplicativo inteiro serve para
        fazer.

        Por isso o tamanho é limitado à *área útil* da tela (que já
        desconta a barra de tarefas), com uma folga para a moldura da
        janela, que não entra nessa conta e existe do lado de fora do
        que `resize` controla. Depois a janela é centralizada nessa
        mesma área, para que nenhuma borda nasça fora dela.
        """
        tela = QGuiApplication.primaryScreen()
        if tela is None:  # pragma: no cover — sessão sem tela
            self.resize(largura, altura)
            return

        util = tela.availableGeometry()
        # Reserva para a barra de título e as bordas do Windows.
        moldura_altura = 48
        moldura_largura = 16

        largura = min(largura, max(self.minimumWidth(), util.width() - moldura_largura))
        altura = min(altura, max(self.minimumHeight(), util.height() - moldura_altura))
        self.resize(largura, altura)
        self.move(
            util.x() + (util.width() - largura) // 2,
            util.y() + max(0, (util.height() - altura - moldura_altura) // 2),
        )

    # --- Construção da UI ------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(22, 16, 22, 20)
        root.setSpacing(14)
        # Guardado porque o peso da área de arrastar muda em tempo de
        # execução (ver `_update_files_section`).
        self._root_layout = root

        root.addLayout(self._build_header())
        root.addWidget(self._build_mode_switch(), 0, Qt.AlignmentFlag.AlignHCenter)

        # Área de drop. O peso 1 é o do estado inicial, com a lista
        # vazia: sem arquivos, arrastar é a única coisa a se fazer na
        # janela, e a área ocupa todo o espaço que sobra.
        self._drop_area = FileDropArea()
        self._drop_area.files_dropped.connect(self._on_files_dropped)
        root.addWidget(self._drop_area, 1)

        # A fala do mascote. A figura dele mora dentro da área de
        # arrastar (ver app/ui/file_drop_area.py), que é onde ela recebe
        # quem chega — repeti-la aqui seria mostrar o mesmo desenho duas
        # vezes na mesma tela.
        self._mascot_label = QLabel()
        self._mascot_label.setObjectName("mascotLabel")
        self._mascot_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self._mascot_label)

        # Lista de arquivos, com o cabeçalho de seção logo acima. Os dois
        # só existem na tela quando há arquivos (`_update_files_section`).
        self._files_header = self._build_files_header()
        root.addWidget(self._files_header)

        self._file_list = FileListWidget()
        self._file_list.files_changed.connect(self._on_files_changed)
        root.addWidget(self._file_list, 1)

        # Seletor de formato (modo Converter), em um cartão da mesma
        # família dos cards de arquivo.
        self._format_card = QFrame()
        self._format_card.setObjectName("formatCard")
        format_row = QHBoxLayout(self._format_card)
        format_row.setContentsMargins(16, 11, 16, 11)
        format_row.setSpacing(12)
        self._format_label = QLabel("Converter para:")
        self._format_selector = FormatSelector(targets_for=self._processor.available_targets)
        self._format_selector.format_selected.connect(lambda _ext: self._update_primary_button())
        format_row.addWidget(self._format_label)
        format_row.addWidget(self._format_selector, 1)
        root.addWidget(self._format_card)

        # O cartão do modo Organizar, no mesmo lugar e da mesma família do
        # cartão de formato: diz qual PDF vai ser organizado — ou o que
        # falta na lista para a operação ficar disponível.
        self._organize_card = QFrame()
        self._organize_card.setObjectName("organizeCard")
        organize_row = QHBoxLayout(self._organize_card)
        organize_row.setContentsMargins(16, 11, 16, 11)
        organize_row.setSpacing(8)
        self._organize_title = QLabel("Organizar as páginas de:")
        self._organize_file = ElidedLabel()
        self._organize_file.setObjectName("cardName")
        self._organize_hint = QLabel()
        self._organize_hint.setObjectName("hintLabel")
        self._organize_hint.setWordWrap(True)
        organize_row.addWidget(self._organize_title)
        organize_row.addWidget(self._organize_file, 1)
        organize_row.addWidget(self._organize_hint, 1)
        root.addWidget(self._organize_card)

        # O que falta instalar para os arquivos da lista — um MP3 sem
        # FFmpeg, um DOCX que não vira PDF sem LibreOffice. Só aparece
        # quando há algo a dizer (ver `dependency_hint`).
        self._dependency_hint = QLabel()
        self._dependency_hint.setObjectName("hintLabel")
        self._dependency_hint.setWordWrap(True)
        self._dependency_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self._dependency_hint)

        # Widget de progresso
        self._progress_widget = ProgressWidget()
        self._progress_widget.cancel_requested.connect(self._batch.cancel)
        root.addWidget(self._progress_widget)

        # Botão principal
        self._primary_button = QPushButton(_PRIMARY_LABELS[CONVERT])
        self._primary_button.setObjectName("primaryButton")
        self._primary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._primary_button.clicked.connect(self._on_primary_clicked)
        root.addWidget(self._primary_button)

        self._update_files_section()
        self._update_primary_button()

    def _build_header(self) -> QHBoxLayout:
        """Ícone do aplicativo, nome, e as duas ações que não são o fluxo.

        As ações secundárias moram em dois botões redondos à direita, e
        não numa barra de menu atravessada no topo de uma janela que não
        tem nada de barra de menu.
        """
        header = QHBoxLayout()
        header.setSpacing(11)

        icone = get_asset(*ICON_PATH)
        if icone is not None:
            logo = QLabel()
            logo.setPixmap(QIcon(str(icone)).pixmap(30, 30))
            header.addWidget(logo)

        titulo_coluna = QVBoxLayout()
        titulo_coluna.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("titleLabel")
        tagline = QLabel("converta, transforme e junte — aqui mesmo")
        tagline.setObjectName("taglineLabel")
        titulo_coluna.addWidget(title)
        titulo_coluna.addWidget(tagline)
        header.addLayout(titulo_coluna)
        header.addStretch()

        settings_button = QPushButton("⚙")
        settings_button.setObjectName("iconButton")
        settings_button.setToolTip("Configurações")
        settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_button.clicked.connect(self._open_settings)

        menu_button = QPushButton("⋯")
        menu_button.setObjectName("iconButton")
        menu_button.setToolTip("Mais opções")
        menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_button.setMenu(self._build_menu())

        header.addWidget(settings_button)
        header.addWidget(menu_button)
        return header

    def _build_mode_switch(self) -> QFrame:
        """Converter / Juntar / Organizar como um controle só, dentro de
        uma cápsula.

        Soltos sobre o fundo, o modo ativo parecia um botão e os outros,
        texto perdido ao lado dele. Na cápsula as partes são visivelmente
        as opções da mesma escolha.
        """
        frame = QFrame()
        frame.setObjectName("modeSwitch")
        row = QHBoxLayout(frame)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(4)

        self._convert_button = QPushButton("CONVERTER")
        self._merge_button = QPushButton("JUNTAR")
        self._organize_button = QPushButton("ORGANIZAR")
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for btn in (self._convert_button, self._merge_button, self._organize_button):
            btn.setObjectName("modeButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(btn)
            self._mode_group.addButton(btn)
        self._convert_button.setChecked(True)

        self._mode_group.buttonClicked.connect(self._on_mode_changed)
        return frame

    def _build_files_header(self) -> QWidget:
        """Título da seção, contagem e o atalho para esvaziar a lista."""
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(8)

        label = QLabel("ARQUIVOS")
        label.setObjectName("sectionLabel")
        self._count_badge = QLabel("0")
        self._count_badge.setObjectName("countBadge")

        self._clear_button = QPushButton("Limpar tudo")
        self._clear_button.setObjectName("linkButton")
        self._clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_button.clicked.connect(self._on_clear_clicked)

        row.addWidget(label)
        row.addWidget(self._count_badge)
        row.addStretch()
        row.addWidget(self._clear_button)
        return bar

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)

        settings_action = menu.addAction("Configurações")
        settings_action.triggered.connect(self._open_settings)

        diagnostics_action = menu.addAction("Diagnóstico e dependências")
        diagnostics_action.triggered.connect(self._open_diagnostics)

        logs_action = menu.addAction("Abrir pasta de logs")
        logs_action.triggered.connect(self._open_logs_folder)

        menu.addSeparator()

        help_action = menu.addAction("Ajuda")
        help_action.triggered.connect(self._show_help)

        about_action = menu.addAction("Sobre")
        about_action.triggered.connect(self._show_about)
        return menu

    def _update_files_section(self) -> None:
        """Ajusta a janela ao fato de haver, ou não, arquivos na lista.

        São dois arranjos da mesma tela. Vazia: uma área de arrastar
        grande, ocupando o que sobra, e nada mais — sem cabeçalho de
        seção sobre uma lista vazia e sem um seletor de formato que só
        pode dizer "nenhum formato disponível". Com arquivos: a área
        vira uma faixa, e a altura passa toda para a lista, que é o que
        o usuário quer ver e conferir a partir dali.
        """
        has_files = not self._file_list.is_empty()
        running = self._batch.is_running()

        self._files_header.setVisible(has_files)
        self._file_list.setVisible(has_files)
        # O cartão do formato também sai de cena enquanto um lote roda:
        # a escolha já foi feita, e o lugar dele na coluna é justamente
        # onde o cartão de progresso precisa aparecer.
        self._format_card.setVisible(has_files and self._mode == CONVERT and not running)
        self._organize_card.setVisible(has_files and self._mode == ORGANIZE and not running)
        self._update_dependency_hint(has_files and not running)

        self._drop_area.set_compact(has_files)
        self._root_layout.setStretchFactor(self._drop_area, 0 if has_files else 1)

        self._count_badge.setText(str(self._file_list.count()))

    def _update_dependency_hint(self, visible: bool) -> None:
        """Mostra o que falta instalar para os arquivos da lista.

        Conta o que as conversões registradas na abertura oferecem, e não o
        que está instalado agora: um programa instalado com o FileMorph
        aberto só entra em uso depois de reiniciar, e a frase precisa
        continuar valendo até lá.
        """
        hint = None
        if visible:
            hint = dependency_hint(
                [get_extension(p) for p in self._file_list.get_paths()],
                self._mode,
                ffmpeg_available=bool(
                    self._processor.available_targets(["mp3"])
                    or self._processor.available_targets(["mp4"])
                ),
                libreoffice_available=self._processor.can_convert("docx", "pdf"),
            )
        self._dependency_hint.setText(hint or "")
        self._dependency_hint.setVisible(bool(hint))

    def _on_clear_clicked(self) -> None:
        """Esvazia a lista. Bloqueado durante um lote: tirar da tela os
        arquivos que a fila está processando só criaria uma divergência
        entre o que a janela mostra e o que está acontecendo."""
        if self._batch.is_running():
            return
        self._file_list.clear()

    def _apply_theme(self) -> None:
        theme_name = resolve_theme_name(settings_manager.settings.theme)
        palette = get_palette(theme_name)
        self.setStyleSheet(build_stylesheet(palette))
        self._apply_primary_shadow(palette)

    def _apply_primary_shadow(self, palette: Palette) -> None:
        """A única sombra da janela, sob o botão principal.

        O QSS do Qt não tem `box-shadow`, então ela é um efeito de
        Python — e precisa ser refeita a cada troca de tema, porque a
        cor sai do destaque do tema atual (ver `shadow_color`). Ela
        desliga junto com o botão: um botão apagado que ainda projeta
        sombra parece clicável, que é justamente o contrário do que o
        estado desabilitado quer dizer.
        """
        sombra = QGraphicsDropShadowEffect(self._primary_button)
        r, g, b = shadow_color(palette)
        sombra.setColor(QColor(r, g, b, 105))
        sombra.setBlurRadius(26)
        sombra.setOffset(0, 7)
        sombra.setEnabled(self._primary_button.isEnabled())
        self._primary_button.setGraphicsEffect(sombra)
        self._primary_shadow = sombra

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
        """Aplica as duas opções do mascote — a fala e o movimento."""
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
        self._update_files_section()
        self._update_primary_button()
        if self._file_list.is_empty():
            self._say("idle")

    def _on_mode_changed(self) -> None:
        if self._organize_button.isChecked():
            self._mode = ORGANIZE
        elif self._merge_button.isChecked():
            self._mode = MERGE
        else:
            self._mode = CONVERT
        # Nos modos Juntar e Organizar não há formato a escolher: a junção
        # sempre produz um PDF, a organização grava o mesmo formato do
        # original, e nos dois casos o nome do arquivo é pedido na hora.
        # Quem troca os cartões da tela é `_update_files_section`, que é
        # também quem os esconde enquanto a lista está vazia.
        self._primary_button.setText(_PRIMARY_LABELS[self._mode])
        self._update_files_section()
        self._update_primary_button()

    # --- Botão principal ---------------------------------------------------

    def _update_primary_button(self) -> None:
        running = self._batch.is_running()
        self._clear_button.setEnabled(not running)

        if running:
            # Há um lote em andamento: o caminho para interromper é o
            # botão "Cancelar" do progresso, não um segundo clique aqui.
            self._set_primary_enabled(False)
            self._primary_button.setToolTip("Processando...")
            return

        paths = self._file_list.get_paths()
        if not paths:
            self._set_primary_enabled(False)
            self._primary_button.setToolTip("Adicione arquivos para começar.")
            return

        if self._mode == CONVERT:
            can_run = self._format_selector.has_valid_selection() and self._processor.can_convert_batch(
                paths, self._format_selector.current_extension() or ""
            )
            tooltip = "" if can_run else "Ainda não há conversão disponível para estes arquivos nesta versão."
        elif self._mode == MERGE:
            can_run = len(paths) >= 2 and self._processor.can_merge(paths)
            tooltip = "" if can_run else "Ainda não há junção disponível para estes arquivos nesta versão."
        else:
            can_run = self._processor.can_organize_pages(paths)
            tooltip = "" if can_run else self._organize_requirement()
            self._update_organize_card(paths, can_run)

        self._set_primary_enabled(can_run)
        self._primary_button.setToolTip(tooltip)

    def _update_organize_card(self, paths: list[str], available: bool) -> None:
        """Mostra qual arquivo vai ser organizado, ou o que falta para a
        operação ficar disponível — no cartão, e não só no tooltip do botão
        apagado, que ninguém vê sem passar o mouse."""
        self._organize_title.setVisible(available)
        self._organize_file.setVisible(available)
        self._organize_hint.setVisible(not available)
        if available:
            self._organize_file.setText(get_filename(paths[0]))
            self._organize_file.setToolTip(paths[0])
        else:
            self._organize_hint.setText(self._organize_requirement())

    def _organize_requirement(self) -> str:
        formats = self._processor.organizable_formats()
        if not formats:
            return "Organizar páginas não está disponível nesta instalação."
        names = " ou ".join(ext.upper() for ext in sorted(formats))
        return f"Para organizar as páginas, deixe apenas um arquivo {names} na lista."

    def _set_primary_enabled(self, enabled: bool) -> None:
        """Liga o botão principal e a sombra dele de uma vez só.

        A sombra é um efeito separado do widget e não sabe sozinha que
        o botão apagou; deixá-la acesa faria um botão desabilitado
        parecer clicável."""
        self._primary_button.setEnabled(enabled)
        if self._primary_shadow is not None:
            self._primary_shadow.setEnabled(enabled)

    def _on_primary_clicked(self) -> None:
        if self._batch.is_running():
            return

        paths = self._file_list.get_paths()
        if not paths:
            return
        output_dir = settings_manager.settings.output_folder

        if self._mode == CONVERT:
            target_ext = self._format_selector.current_extension()
            if not target_ext:
                return

            policy = self._resolve_overwrite_policy(paths, target_ext, output_dir)
            if policy is None:  # usuário cancelou no diálogo de conflito
                return

            # Os destinos de todo o lote são decididos aqui, antes de a
            # primeira tarefa rodar (ver `FileProcessor.plan_conversion`).
            tasks = self._processor.plan_conversion(
                BatchRequest(
                    input_paths=paths,
                    target_extension=target_ext,
                    output_dir=output_dir,
                    overwrite_policy=policy,
                )
            )
            self._batch.start(CONVERT, tasks, output_dir)
        elif self._mode == MERGE:
            output_path = self._ask_merge_destination(paths, output_dir)
            if output_path is None:  # usuário fechou o diálogo
                return
            task = self._processor.plan_merge(paths, output_path)
            self._batch.start(MERGE, [task], str(Path(output_path).parent))
        else:
            self._open_page_organizer(paths[0], output_dir)

    def _open_page_organizer(self, path: str, output_dir: str) -> None:
        """Abre a janela de organização e, se o usuário confirmar a nova
        ordem, grava o PDF novo pela fila — com o mesmo progresso,
        cancelamento e resumo final de qualquer outra operação.

        A janela recebe o tema do momento porque os cards de página são
        pintados à mão, fora do alcance do QSS (ver `PageCardDelegate`).
        """
        palette = get_palette(resolve_theme_name(settings_manager.settings.theme))
        dialog = PageOrganizerDialog(
            path, self._processor.open_page_preview, palette, output_dir, parent=self
        )
        if not dialog.exec():
            return
        output_path = dialog.output_path()
        if output_path is None:
            return
        task = self._processor.plan_organize(path, output_path, dialog.page_order())
        self._batch.start(ORGANIZE, [task], str(Path(output_path).parent))

    def _ask_merge_destination(self, paths: list[str], output_dir: str) -> str | None:
        """Pergunta onde salvar o arquivo final da junção.

        O próprio diálogo do sistema já cuida de confirmar a
        substituição de um arquivo existente. O que ele não sabe é que
        um desses arquivos pode ser uma das entradas — e aí o nome é
        recusado e a pergunta volta. O núcleo recusa de novo se algo
        passar daqui (ver `FileProcessor._merge_one`).
        """
        suggested = str(ensure_directory(output_dir) / "documento_final.pdf")
        while True:
            chosen, _filter = QFileDialog.getSaveFileName(
                self, "Salvar arquivo final", suggested, "PDF (*.pdf)"
            )
            if not chosen:
                return None
            # Em diálogos não nativos a extensão pode não vir junto do nome.
            if get_extension(chosen) != "pdf":
                chosen = f"{chosen}.pdf"
            conflict = self._processor.merge_destination_conflict(paths, chosen)
            if conflict is None:
                return chosen
            QMessageBox.warning(self, "Escolha outro nome", input_conflict_message(conflict))
            suggested = str(Path(chosen).with_name("documento_final.pdf"))

    def _resolve_overwrite_policy(
        self, paths: list[str], target_ext: str, output_dir: str
    ) -> str | None:
        """Pergunta ao usuário o que fazer quando o arquivo de destino já
        existe. Retorna 'replace', 'copy' ou None (cancelar).

        Um destino que é um dos arquivos da própria lista não conta como
        conflito: o planejamento sempre gera uma cópia nesse caso,
        justamente para nunca destruir um original.
        """
        conflicts = [
            path.name
            for path in self._processor.find_conversion_conflicts(paths, target_ext, output_dir)
        ]

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

    # --- Lote em andamento ---------------------------------------------------

    def _on_batch_started(self, total_files: int) -> None:
        self._progress_widget.start(total_files)
        self._update_files_section()
        self._update_primary_button()
        self._say("processing")

    def _on_file_updated(self, update: FileUpdate) -> None:
        self._file_list.set_status(update.path, update.status, update.message)

    def _on_progress_changed(self, files_done: int, percent: int) -> None:
        self._progress_widget.report(files_done, percent)

    def _progress_widget_current_file(self, name: str) -> None:
        self._progress_widget.update_current_file(name)

    def _on_batch_finished(self, summary: BatchSummary) -> None:
        self._progress_widget.finish()
        self._update_files_section()
        self._update_primary_button()

        succeeded = len(summary.succeeded)
        folder = summary.output_folder

        if summary.cancelled:
            self._say("cancelled")
            self._show_summary(
                "Operação cancelada",
                f"Operação interrompida. {succeeded} arquivo(s) já tinham sido "
                f"concluídos; {len(summary.stopped)} não chegaram a ser processados.",
                folder=folder if succeeded else None,
            )
            return

        if summary.failed:
            self._say("partial" if succeeded else "error")
            details = "\n".join(f"• {get_filename(p)}: {msg}" for p, msg in summary.failed[:8])
            if len(summary.failed) > 8:
                details += f"\n... e mais {len(summary.failed) - 8} arquivo(s)"
            opened = self._show_summary(
                "Concluído com erros",
                f"{succeeded} arquivo(s) concluído(s), {len(summary.failed)} com erro:\n\n{details}",
                warning=True,
                folder=folder if succeeded else None,
            )
        else:
            self._say("done")
            if summary.kind == MERGE and summary.output_path:
                text = f"{succeeded} arquivo(s) unido(s) em:\n{summary.output_path}"
            elif summary.kind == ORGANIZE and summary.output_path:
                text = f"PDF salvo com a nova ordem das páginas em:\n{summary.output_path}"
            else:
                text = f"{succeeded} arquivo(s) salvo(s) em:\n{folder}"
            opened = self._show_summary("Tudo pronto", text, folder=folder)

        if succeeded and not opened and settings_manager.settings.open_folder_after_finish:
            self._open_folder(folder)

    def _show_summary(
        self, title: str, text: str, *, warning: bool = False, folder: str | None = None
    ) -> bool:
        """O aviso de fim de lote, com um botão para abrir a pasta do
        resultado. Devolve True se o usuário usou o botão — e aí a pasta
        não é aberta uma segunda vez pela opção automática."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(text)
        open_button = None
        if folder:
            open_button = box.addButton("Abrir pasta", QMessageBox.ButtonRole.ActionRole)
        ok_button = box.addButton(QMessageBox.StandardButton.Ok)
        box.setDefaultButton(ok_button)
        box.exec()
        if open_button is not None and box.clickedButton() is open_button:
            self._open_folder(folder)
            return True
        return False

    @staticmethod
    def _open_folder(folder: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # --- Dependências e diagnóstico -----------------------------------------

    def _log_dependencies(self) -> None:
        """Registra no log o que falta nesta máquina. A detecção já aconteceu
        no registro dos conversores, então aqui não roda processo nenhum."""
        if not ffmpeg_manager.status().available:
            logger.info("FFmpeg não encontrado — conversões de áudio/vídeo ficarão indisponíveis.")
        if not libreoffice_manager.status().available:
            logger.info(
                "LibreOffice não encontrado — DOCX e XLSX para PDF ficarão "
                "indisponíveis."
            )

    def _open_diagnostics(self) -> None:
        """Mostra versão, Windows, pastas e a situação do FFmpeg e do
        LibreOffice.

        A detecção dos programas é refeita aqui: se o usuário instalou um
        deles com o FileMorph aberto, a janela o encontra — e diz que falta
        reiniciar, porque as conversões são registradas na abertura.
        """
        logs_dir = str(get_logs_dir())
        report = collect_diagnostics(
            output_folder=settings_manager.settings.output_folder,
            data_dir=str(get_app_data_dir()),
            logs_dir=logs_dir,
            ffmpeg_active_formats=(
                self._processor.available_targets(["mp3"])
                | self._processor.available_targets(["mp4"])
            ),
            libreoffice_active=self._processor.can_convert("docx", "pdf"),
            qt_version=PYSIDE_VERSION,
        )
        DiagnosticsDialog(report, logs_dir, parent=self).exec()

    # --- Menu ---------------------------------------------------------------

    def _open_settings(self) -> None:
        dialog = SettingsWindow(settings_manager, parent=self)
        if dialog.exec():
            self._task_queue.set_max_concurrent(settings_manager.settings.max_concurrent_tasks)
            ffmpeg_manager.set_configured_path(settings_manager.settings.ffmpeg_path)
            self._apply_theme()
            self._apply_mascot_settings()

    def _open_logs_folder(self) -> None:
        self._open_folder(str(get_logs_dir()))

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "Ajuda",
            "Arraste seus arquivos para a área central, escolha o formato de "
            "destino (ou o modo Juntar) e clique no botão principal.\n\n"
            "Esta versão converte imagens entre PNG, JPG e WEBP, transforma "
            "imagens em PDF e PDF em imagens, converte áudio entre MP3, WAV, "
            "FLAC, OGG e M4A, converte vídeo entre MP4, MKV e WEBM, extrai a "
            "trilha sonora de um vídeo como arquivo de áudio, converte "
            "documentos entre DOCX, TXT e PDF e planilhas entre XLSX e CSV. "
            "Os arquivos convertidos são salvos na pasta definida em "
            "Configurações, e o original nunca é alterado.\n\n"
            "No modo Juntar, vários PDFs, imagens, documentos e planilhas "
            "viram um único PDF, na ordem em que aparecem na lista.\n\n"
            "No modo Organizar, um PDF abre numa janela com a miniatura de cada "
            "página: arraste as páginas para mudar a ordem e salve um PDF novo. "
            "Nenhuma página é perdida ou duplicada, a qualidade continua a "
            "mesma e o PDF original não é alterado.\n\n"
            "Uma planilha de várias abas vira uma pasta com um CSV por aba, "
            "porque um arquivo CSV guarda uma tabela só. E vindo do CSV, "
            "apenas o que é inequivocamente número vira número: um CEP ou um "
            "código com zero à esquerda continua texto, para não perder o "
            "zero.\n\n"
            "Ir para TXT guarda só o texto: negrito, imagens e layout não "
            "cabem em um arquivo de texto, e isso vale para qualquer "
            "programa. Um PDF digitalizado também não tem texto por dentro — é "
            "a imagem de uma página —, e o FileMorph não faz reconhecimento de "
            "texto.\n\n"
            "Áudio e vídeo dependem do FFmpeg, e DOCX ou XLSX → PDF dependem do "
            "LibreOffice: use 'Diagnóstico e dependências' no botão ⋯ do "
            "cabeçalho para ver o que está habilitado nesta máquina e onde "
            "instalar o que falta. Converter vídeo é demorado — leva na ordem "
            "da duração do próprio vídeo —, e o botão Cancelar interrompe a "
            "conversão em andamento a qualquer momento.",
        )

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            f"Sobre o {APP_NAME}",
            f"{APP_NAME} {__version__}\n\n"
            "Converta, transforme, junte e organize arquivos localmente — "
            "nenhum arquivo sai do seu computador.\n\n"
            "Imagens PNG, JPG e WEBP; PDF; documentos DOCX e TXT; planilhas "
            "XLSX e CSV; áudio e vídeo com o FFmpeg; junção em PDF e "
            "organização das páginas de um PDF.\n\n"
            f"{APP_URL}",
        )
