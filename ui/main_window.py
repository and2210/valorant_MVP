from __future__ import annotations

import calendar
from datetime import date

from pynput import keyboard, mouse
from PySide6.QtCore import QDate, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.app_controller import AppController
from core.input_timing import InputTimingTracker
from core.config import DATA_DIR, AppConfig, load_config, save_config
from core.dashboard import DashboardStats
from core.tracker_importer import (
    build_ranked_radiante_stats,
    build_training_calendar,
    get_tracker_settings,
    load_tracker_dm_matches,
    load_tracker_ranked_matches,
)


class GuiSignals(QObject):
    toggle_session_requested = Signal()
    reset_requested = Signal()
    refresh_requested = Signal()
    shutdown_requested = Signal()


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.controller = AppController()
        self.signals = GuiSignals()
        self.keyboard_listener = None
        self.mouse_listener = None
        self.setWindowTitle("MVP APP — Valorant Training / KCred")
        self.resize(1180, 820)
        self.setMinimumSize(980, 680)
        self.current_calendar_month = date.today().replace(day=1)
        self.app_config = load_config()
        self.calendar_settings = self.app_config.training_calendar

        self._build_ui()
        self._connect_signals()
        self._start_input_listeners()

        self.live_timer = QTimer(self)
        self.live_timer.timeout.connect(self.refresh_runtime_state)
        self.live_timer.start(500)

        self.refresh_all()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        title = QLabel("MVP APP — Valorant Training / KCred")
        title.setObjectName("TitleLabel")
        root.addWidget(title)

        self.status_label = QLabel("Status: DESLIGADO")
        root.addWidget(self.status_label)

        button_row = QHBoxLayout()
        self.session_mode_combo = QComboBox()
        self.session_mode_combo.addItem("Deathmatch (KCred)", "deathmatch")
        self.session_mode_combo.addItem("Ranked (audit only)", "ranked")
        self.start_button = QPushButton("Iniciar DM (F10)")
        self.finish_button = QPushButton("Encerrar DM (F10)")
        self.reset_button = QPushButton("Resetar contadores (F9)")
        self.refresh_button = QPushButton("Atualizar (F6)")
        self.finish_button.setEnabled(False)
        button_row.addWidget(QLabel("Modo:"))
        button_row.addWidget(self.session_mode_combo)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.finish_button)
        button_row.addWidget(self.reset_button)
        button_row.addWidget(self.refresh_button)
        button_row.addStretch(1)
        root.addLayout(button_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_dm_tab(), "DM atual / Dashboard")
        self.tabs.addTab(self._build_tracker_tab(), "Tracker / DMs reais")
        self.tabs.addTab(self._build_radiante_tab(), "Radiante / Ranked")
        self.tabs.addTab(self._build_calendar_tab(), "Calendário")
        self.tabs.addTab(self._build_settings_tab(), "Configurações")
        root.addWidget(self.tabs, stretch=1)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        root.addWidget(line)

        info_group = QGroupBox("Importação Tracker")
        info_layout = QHBoxLayout(info_group)
        self.info_tracker_label = QLabel("Tracker: pronto")
        self.info_tracker_progress_bar = QProgressBar()
        self.info_tracker_progress_bar.setRange(0, 1000)
        self.info_tracker_progress_bar.setValue(0)
        self.info_tracker_progress_bar.setFormat("0.0%")
        info_layout.addWidget(self.info_tracker_label)
        info_layout.addWidget(self.info_tracker_progress_bar, stretch=1)
        root.addWidget(info_group)

        self.setStyleSheet(
            """
            QLabel#TitleLabel {
                font-size: 20px;
                font-weight: bold;
            }
            QGroupBox {
                font-weight: bold;
            }
            QTableWidget {
                font-family: Consolas, monospace;
            }
            """
        )

    def _build_dm_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)

        dashboard_group = QGroupBox("Dashboard local")
        dashboard_layout = QGridLayout(dashboard_group)

        self.level_label = QLabel("Nível: -")
        self.xp_label = QLabel("XP: -")
        self.xp_bar = QProgressBar()
        self.xp_bar.setRange(0, 1000)
        self.xp_bar.setValue(0)
        self.xp_bar.setTextVisible(True)
        self.balance_label = QLabel("Saldo: -")
        self.next_weapon_label = QLabel("Próxima arma: -")
        self.total_sessions_label = QLabel("Sessões totais: -")
        self.avg_rate_label = QLabel("Taxa média geral: -")
        self.best_weapon_label = QLabel("Melhor arma: -")
        self.today_label = QLabel("Hoje: -")

        dashboard_layout.addWidget(self.level_label, 0, 0)
        dashboard_layout.addWidget(self.xp_label, 0, 1)
        dashboard_layout.addWidget(self.xp_bar, 1, 0, 1, 2)
        dashboard_layout.addWidget(self.balance_label, 2, 0)
        dashboard_layout.addWidget(self.next_weapon_label, 2, 1)
        dashboard_layout.addWidget(self.total_sessions_label, 3, 0)
        dashboard_layout.addWidget(self.avg_rate_label, 3, 1)
        dashboard_layout.addWidget(self.best_weapon_label, 4, 0)
        dashboard_layout.addWidget(self.today_label, 4, 1)
        root.addWidget(dashboard_group)

        live_group = QGroupBox("Sessão atual")
        live_layout = QGridLayout(live_group)

        self.current_weapon_label = QLabel("Arma da sessão: -")
        self.clean_hits_label = QLabel("Acertos limpos: 0")
        self.brake_errors_label = QLabel("Erros de freio: 0")
        self.diagonal_errors_label = QLabel("Erros de diagonal: 0")
        self.no_ad_errors_label = QLabel("Sem A/D (legado): desativado")
        self.valid_attempts_label = QLabel("Tentativas válidas: 0")
        self.ignored_clicks_label = QLabel("Cliques ignorados: 0")
        self.current_rate_label = QLabel("Taxa atual: 0.0%")
        self.current_kcred_label = QLabel("KCred desta sessão: +0")

        self.current_kcred_label.setStyleSheet("font-weight: bold; color: #FACC15;")

        live_layout.addWidget(self.current_weapon_label, 0, 0)
        live_layout.addWidget(self.current_rate_label, 0, 1)
        live_layout.addWidget(self.current_kcred_label, 1, 0)
        live_layout.addWidget(self.clean_hits_label, 1, 1)
        live_layout.addWidget(self.brake_errors_label, 2, 0)
        live_layout.addWidget(self.diagonal_errors_label, 2, 1)
        live_layout.addWidget(self.no_ad_errors_label, 3, 0)
        live_layout.addWidget(self.valid_attempts_label, 3, 1)
        live_layout.addWidget(self.ignored_clicks_label, 4, 0)
        root.addWidget(live_group)

        input_group = QGroupBox("Input timing — medição da sessão")
        input_layout = QGridLayout(input_group)
        self.fire_profile_label = QLabel("Tiro: tap 0 | burst 0 | spray longo 0")
        self.fire_duration_label = QLabel("Duração tiro: média 0.00s | máx 0.00s")
        self.fire_context_label = QLabel("Tiro W/S: 0 | crouch+tiro: 0 | crouch longo: 0")
        self.input_motion_label = QLabel("Diagonal: 0x | 0.00s")
        self.input_actions_label = QLabel("Inputs: teclas 0 | mouse 0 | scroll 0 | scroll jump 0")
        input_layout.addWidget(self.fire_profile_label, 0, 0, 1, 2)
        input_layout.addWidget(self.fire_duration_label, 1, 0, 1, 2)
        input_layout.addWidget(self.fire_context_label, 2, 0, 1, 2)
        input_layout.addWidget(self.input_motion_label, 3, 0)
        input_layout.addWidget(self.input_actions_label, 3, 1)
        root.addWidget(input_group)

        purchase_group = QGroupBox("Compra da próxima arma")
        purchase_layout = QHBoxLayout(purchase_group)
        self.weapon_combo = QComboBox()
        self.weapon_combo.setMinimumWidth(320)
        self.weapon_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.weapon_combo.setMinimumContentsLength(28)
        self.confirm_purchase_button = QPushButton("Confirmar compra")
        self.purchase_status_label = QLabel("Finalize uma sessão para liberar a compra.")

        self.weapon_combo.setEnabled(False)
        self.confirm_purchase_button.setEnabled(False)

        purchase_layout.addWidget(self.weapon_combo, stretch=1)
        purchase_layout.addWidget(self.confirm_purchase_button)
        purchase_layout.addWidget(self.purchase_status_label, stretch=2)
        root.addWidget(purchase_group)
        root.addStretch(1)
        return tab

    def _build_tracker_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)

        actions = QHBoxLayout()
        self.import_tracker_button = QPushButton("Importar DMs")
        self.import_all_tracker_checkbox = QCheckBox("Importar todos dentro do limite")
        self.import_all_tracker_checkbox.setChecked(True)
        self.import_day_button = QPushButton("Atualizar dia")
        self.import_range_button = QPushButton("Atualizar intervalo")
        self.import_from_date = QDateEdit()
        self.import_from_date.setCalendarPopup(True)
        self.import_from_date.setDisplayFormat("yyyy-MM-dd")
        self.import_from_date.setDate(QDate.currentDate())
        self.import_to_date = QDateEdit()
        self.import_to_date.setCalendarPopup(True)
        self.import_to_date.setDisplayFormat("yyyy-MM-dd")
        self.import_to_date.setDate(QDate.currentDate())
        actions.addWidget(self.import_tracker_button)
        actions.addWidget(self.import_all_tracker_checkbox)
        actions.addWidget(QLabel("De:"))
        actions.addWidget(self.import_from_date)
        actions.addWidget(QLabel("Até:"))
        actions.addWidget(self.import_to_date)
        actions.addWidget(self.import_day_button)
        actions.addWidget(self.import_range_button)
        actions.addStretch(1)
        root.addLayout(actions)

        tracker_group = QGroupBox("Estatísticas reais importadas")
        tracker_layout = QGridLayout(tracker_group)
        self.tracker_total_label = QLabel("DMs importados: 0")
        self.tracker_kd_label = QLabel("KD médio: -")
        self.tracker_best_map_label = QLabel("Melhor mapa: -")
        self.tracker_best_agent_label = QLabel("Melhor agente: -")
        self.tracker_best_match_label = QLabel("Melhor DM: -")
        self.tracker_last_match_label = QLabel("Último DM: -")

        tracker_layout.addWidget(self.tracker_total_label, 0, 0)
        tracker_layout.addWidget(self.tracker_kd_label, 0, 1)
        tracker_layout.addWidget(self.tracker_best_map_label, 1, 0)
        tracker_layout.addWidget(self.tracker_best_agent_label, 1, 1)
        tracker_layout.addWidget(self.tracker_best_match_label, 2, 0)
        tracker_layout.addWidget(self.tracker_last_match_label, 2, 1)
        root.addWidget(tracker_group)

        self.tracker_table = QTableWidget(0, 10)
        self.tracker_table.setHorizontalHeaderLabels([
            "Data", "Mapa", "Agente", "K", "D", "A", "KD", "Duração", "Arma", "Protocolo"
        ])
        self.tracker_table.setMinimumHeight(260)
        root.addWidget(self.tracker_table, stretch=1)
        return tab

    def _build_radiante_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)

        actions = QHBoxLayout()
        self.import_ranked_button = QPushButton("Importar Rankeds")
        self.import_all_ranked_checkbox = QCheckBox("Importar todas dentro do limite")
        self.import_all_ranked_checkbox.setChecked(True)
        self.import_ranked_day_button = QPushButton("Atualizar dia")
        self.import_ranked_range_button = QPushButton("Atualizar intervalo")
        self.ranked_from_date = QDateEdit()
        self.ranked_from_date.setCalendarPopup(True)
        self.ranked_from_date.setDisplayFormat("yyyy-MM-dd")
        self.ranked_from_date.setDate(QDate.currentDate())
        self.ranked_to_date = QDateEdit()
        self.ranked_to_date.setCalendarPopup(True)
        self.ranked_to_date.setDisplayFormat("yyyy-MM-dd")
        self.ranked_to_date.setDate(QDate.currentDate())

        actions.addWidget(self.import_ranked_button)
        actions.addWidget(self.import_all_ranked_checkbox)
        actions.addWidget(QLabel("De:"))
        actions.addWidget(self.ranked_from_date)
        actions.addWidget(QLabel("Até:"))
        actions.addWidget(self.ranked_to_date)
        actions.addWidget(self.import_ranked_day_button)
        actions.addWidget(self.import_ranked_range_button)
        actions.addStretch(1)
        root.addLayout(actions)

        summary_group = QGroupBox("Radiante — análise competitiva")
        summary_layout = QGridLayout(summary_group)
        self.ranked_total_label = QLabel("Rankeds: 0")
        self.ranked_winrate_label = QLabel("Winrate: -")
        self.ranked_rr_label = QLabel("RR: -")
        self.ranked_acs_label = QLabel("ACS médio: -")
        self.ranked_adr_label = QLabel("ADR médio: -")
        self.ranked_dd_label = QLabel("DDΔ: -")
        self.ranked_fbfd_label = QLabel("FB/FD: -")
        self.ranked_kast_label = QLabel("KAST: -")
        self.ranked_signal_label = QLabel("Sinal dominante: -")
        self.ranked_focus_label = QLabel("Foco recomendado: -")
        self.ranked_best_map_label = QLabel("Melhor mapa: -")
        self.ranked_worst_map_label = QLabel("Pior mapa: -")

        summary_layout.addWidget(self.ranked_total_label, 0, 0)
        summary_layout.addWidget(self.ranked_winrate_label, 0, 1)
        summary_layout.addWidget(self.ranked_rr_label, 0, 2)
        summary_layout.addWidget(self.ranked_acs_label, 1, 0)
        summary_layout.addWidget(self.ranked_adr_label, 1, 1)
        summary_layout.addWidget(self.ranked_kast_label, 1, 2)
        summary_layout.addWidget(self.ranked_dd_label, 2, 0)
        summary_layout.addWidget(self.ranked_fbfd_label, 2, 1)
        summary_layout.addWidget(self.ranked_best_map_label, 2, 2)
        summary_layout.addWidget(self.ranked_worst_map_label, 3, 0)
        summary_layout.addWidget(self.ranked_signal_label, 3, 1, 1, 2)
        summary_layout.addWidget(self.ranked_focus_label, 4, 0, 1, 3)
        root.addWidget(summary_group)

        self.ranked_table = QTableWidget(0, 14)
        self.ranked_table.setHorizontalHeaderLabels([
            "Data", "Mapa", "Agente", "Resultado", "Rank", "RRΔ",
            "ACS", "ADR", "DDΔ", "DD/R", "FB", "FD", "FB-FD", "K/D/A"
        ])
        self.ranked_table.setMinimumHeight(360)
        root.addWidget(self.ranked_table, stretch=1)
        return tab

    def _build_calendar_tab(self) -> QWidget:
        tab = QWidget()
        root = QVBoxLayout(tab)

        calendar_group = QGroupBox("Calendário de treino")
        calendar_layout = QVBoxLayout(calendar_group)

        calendar_actions = QHBoxLayout()
        self.prev_month_button = QPushButton("◀ Mês anterior")
        self.calendar_month_label = QLabel("-")
        self.calendar_month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.today_month_button = QPushButton("Mês atual")
        self.next_month_button = QPushButton("Próximo mês ▶")
        self.export_calendar_button = QPushButton("Exportar mês CSV")
        calendar_actions.addWidget(self.prev_month_button)
        calendar_actions.addWidget(self.calendar_month_label, stretch=1)
        calendar_actions.addWidget(self.today_month_button)
        calendar_actions.addWidget(self.next_month_button)
        calendar_actions.addWidget(self.export_calendar_button)
        calendar_layout.addLayout(calendar_actions)

        self.calendar_month_summary_label = QLabel("Mês: -")
        self.calendar_goal_label = QLabel("Meta diária: -")
        calendar_layout.addWidget(self.calendar_month_summary_label)
        calendar_layout.addWidget(self.calendar_goal_label)

        self.training_calendar_table = QTableWidget(6, 7)
        self.training_calendar_table.setHorizontalHeaderLabels([
            "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"
        ])
        self.training_calendar_table.setVerticalHeaderLabels(["1", "2", "3", "4", "5", "6"])
        self.training_calendar_table.setMinimumHeight(260)
        self.training_calendar_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.training_calendar_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.training_calendar_table.setWordWrap(True)
        calendar_layout.addWidget(self.training_calendar_table)

        self.calendar_legend_label = QLabel(self.get_calendar_legend_text())
        calendar_layout.addWidget(self.calendar_legend_label)

        self.training_days_summary_table = QTableWidget(0, 7)
        self.training_days_summary_table.setHorizontalHeaderLabels([
            "Data", "DMs", "Tempo", "Horas", "KD médio", "Sessões vinculadas", "Armas"
        ])
        self.training_days_summary_table.setMinimumHeight(130)
        calendar_layout.addWidget(self.training_days_summary_table)
        root.addWidget(calendar_group, stretch=1)
        return tab

    def _build_settings_tab(self) -> QWidget:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        root = QVBoxLayout(content)

        info_label = QLabel(
            "Configurações rápidas do app. Salve somente fora de uma sessão ativa. "
            "Alterações de protocolo e input timing valem a partir da próxima sessão."
        )
        info_label.setWordWrap(True)
        root.addWidget(info_label)

        economy_group = QGroupBox("Economia e progressão")
        economy_form = QFormLayout(economy_group)
        self.setting_kcred_clean = self.make_int_spin(0, 1000)
        self.setting_penalty_brake = self.make_int_spin(0, 1000)
        self.setting_penalty_diagonal = self.make_int_spin(0, 1000)
        self.setting_penalty_no_ad = self.make_int_spin(0, 1000)
        self.setting_xp_clean = self.make_int_spin(0, 1000)
        self.setting_xp_level = self.make_int_spin(1, 1_000_000)
        economy_form.addRow("KCred por acerto limpo:", self.setting_kcred_clean)
        economy_form.addRow("Penalidade erro de freio:", self.setting_penalty_brake)
        economy_form.addRow("Penalidade erro diagonal:", self.setting_penalty_diagonal)
        economy_form.addRow("Penalidade erro sem A/D:", self.setting_penalty_no_ad)
        economy_form.addRow("XP por acerto limpo:", self.setting_xp_clean)
        economy_form.addRow("XP por nível:", self.setting_xp_level)
        root.addWidget(economy_group)

        protocol_group = QGroupBox("Protocolo DM")
        protocol_form = QFormLayout(protocol_group)
        self.setting_episode_timeout = self.make_seconds_spin(0.10, 10.00)
        self.setting_click_cooldown = self.make_seconds_spin(0.00, 5.00)
        self.setting_stationary_clean = QCheckBox("Clique parado conta como acerto limpo")
        self.setting_stationary_release = self.make_seconds_spin(0.00, 2.00)
        self.setting_require_release = QCheckBox("Exigir soltar A/D no momento do clique")
        protocol_form.addRow("Tempo máximo do episódio:", self.setting_episode_timeout)
        protocol_form.addRow("Cooldown pós-clique:", self.setting_click_cooldown)
        protocol_form.addRow("Disparo parado:", self.setting_stationary_clean)
        protocol_form.addRow("Tempo mínimo parado:", self.setting_stationary_release)
        protocol_form.addRow("Regra extra:", self.setting_require_release)
        root.addWidget(protocol_group)

        input_group = QGroupBox("Input timing")
        input_form = QFormLayout(input_group)
        self.setting_input_enabled = QCheckBox("Medir duração de teclas, mouse e scroll")
        self.setting_tap_max = self.make_seconds_spin(0.01, 2.00)
        self.setting_burst_max = self.make_seconds_spin(0.05, 5.00)
        self.setting_crouch_fire_max = self.make_seconds_spin(0.05, 5.00)
        input_form.addRow("Input timing:", self.setting_input_enabled)
        input_form.addRow("Tap máximo:", self.setting_tap_max)
        input_form.addRow("Burst máximo:", self.setting_burst_max)
        input_form.addRow("Crouch+tiro máximo:", self.setting_crouch_fire_max)
        root.addWidget(input_group)

        calendar_group = QGroupBox("Calendário")
        calendar_form = QFormLayout(calendar_group)
        self.setting_daily_goal = self.make_hours_spin(0.10, 24.00)
        self.setting_light_day = self.make_hours_spin(0.10, 24.00)
        self.setting_medium_day = self.make_hours_spin(0.10, 24.00)
        self.setting_strong_day = self.make_hours_spin(0.10, 24.00)
        calendar_form.addRow("Meta diária de treino:", self.setting_daily_goal)
        calendar_form.addRow("Dia leve a partir de:", self.setting_light_day)
        calendar_form.addRow("Dia médio a partir de:", self.setting_medium_day)
        calendar_form.addRow("Dia forte a partir de:", self.setting_strong_day)
        root.addWidget(calendar_group)

        tracker_group = QGroupBox("Importação Tracker/Henrik")
        tracker_form = QFormLayout(tracker_group)
        self.setting_riot_name = QLineEdit()
        self.setting_riot_tag = QLineEdit()
        self.setting_region = QLineEdit()
        self.setting_platform = QLineEdit()
        self.setting_api_key = QLineEdit()
        self.setting_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.setting_show_api_key = QCheckBox("Mostrar chave")
        self.setting_api_key_status = QLabel("Chave Henrik: não verificada")
        self.setting_import_limit = self.make_int_spin(1, 5000)
        self.setting_max_scan = self.make_int_spin(10, 20000)
        self.setting_request_delay = self.make_seconds_spin(0.00, 60.00)
        self.setting_ranked_detail_enrichment = QCheckBox("Buscar detalhe das rankeds para tentar preencher FK/FD")
        tracker_form.addRow("Riot name:", self.setting_riot_name)
        tracker_form.addRow("Riot tag:", self.setting_riot_tag)
        tracker_form.addRow("Região:", self.setting_region)
        tracker_form.addRow("Plataforma:", self.setting_platform)
        tracker_form.addRow("Chave Henrik API:", self.setting_api_key)
        tracker_form.addRow("Visualização da chave:", self.setting_show_api_key)
        tracker_form.addRow("Status da chave:", self.setting_api_key_status)
        tracker_form.addRow("Limite padrão de importação:", self.setting_import_limit)
        tracker_form.addRow("Máximo de partidas varridas:", self.setting_max_scan)
        tracker_form.addRow("Delay entre requisições:", self.setting_request_delay)
        tracker_form.addRow("Enriquecer Ranked:", self.setting_ranked_detail_enrichment)
        root.addWidget(tracker_group)

        actions = QHBoxLayout()
        self.reload_settings_button = QPushButton("Recarregar")
        self.reset_settings_button = QPushButton("Restaurar padrões na tela")
        self.save_settings_button = QPushButton("Salvar configurações")
        self.settings_status_label = QLabel("Pronto.")
        actions.addWidget(self.reload_settings_button)
        actions.addWidget(self.reset_settings_button)
        actions.addWidget(self.save_settings_button)
        actions.addWidget(self.settings_status_label, stretch=1)
        root.addLayout(actions)
        root.addStretch(1)

        self.load_settings_into_form(self.app_config)
        scroll.setWidget(content)
        tab_layout.addWidget(scroll)
        return tab

    def _connect_signals(self) -> None:
        self.start_button.clicked.connect(self.start_session)
        self.finish_button.clicked.connect(self.finish_session)
        self.reset_button.clicked.connect(self.reset_counters)
        self.refresh_button.clicked.connect(self.refresh_all)
        self.confirm_purchase_button.clicked.connect(self.confirm_purchase)
        self.session_mode_combo.currentIndexChanged.connect(self.change_session_mode)
        self.import_tracker_button.clicked.connect(self.import_tracker_deathmatches)
        self.import_day_button.clicked.connect(self.import_tracker_selected_day)
        self.import_range_button.clicked.connect(self.import_tracker_selected_range)
        self.import_ranked_button.clicked.connect(self.import_tracker_rankeds)
        self.import_ranked_day_button.clicked.connect(self.import_ranked_selected_day)
        self.import_ranked_range_button.clicked.connect(self.import_ranked_selected_range)
        self.prev_month_button.clicked.connect(self.show_previous_month)
        self.today_month_button.clicked.connect(self.show_current_month)
        self.next_month_button.clicked.connect(self.show_next_month)
        self.export_calendar_button.clicked.connect(self.export_current_month_calendar)
        self.save_settings_button.clicked.connect(self.save_quick_settings)
        self.reload_settings_button.clicked.connect(self.reload_quick_settings)
        self.reset_settings_button.clicked.connect(self.reset_quick_settings_to_defaults)
        self.setting_show_api_key.toggled.connect(self.toggle_api_key_visibility)

        self.signals.toggle_session_requested.connect(self.toggle_session)
        self.signals.reset_requested.connect(self.reset_counters)
        self.signals.refresh_requested.connect(self.refresh_all)
        self.signals.shutdown_requested.connect(self.close)

    # ------------------------------------------------------------------
    # Configurações rápidas
    # ------------------------------------------------------------------

    @staticmethod
    def make_int_spin(minimum: int, maximum: int) -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setSingleStep(1)
        return widget

    @staticmethod
    def make_seconds_spin(minimum: float, maximum: float) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setSingleStep(0.05)
        widget.setDecimals(3)
        widget.setSuffix(" s")
        return widget

    @staticmethod
    def make_hours_spin(minimum: float, maximum: float) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setSingleStep(0.25)
        widget.setDecimals(2)
        widget.setSuffix(" h")
        return widget

    def toggle_api_key_visibility(self, checked: bool) -> None:
        self.setting_api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def refresh_api_key_status(self) -> None:
        config_key = self.setting_api_key.text().strip()
        active_settings = get_tracker_settings()
        if config_key:
            self.setting_api_key_status.setText("Chave Henrik: configurada no app")
        elif active_settings.api_key:
            self.setting_api_key_status.setText("Chave Henrik: usando .env/variável de ambiente")
        else:
            self.setting_api_key_status.setText("Chave Henrik: ausente")

    def load_settings_into_form(self, config: AppConfig) -> None:
        self.setting_kcred_clean.setValue(int(config.kcred_per_clean_hit))
        self.setting_penalty_brake.setValue(int(config.kcred_penalty_brake_error))
        self.setting_penalty_diagonal.setValue(int(config.kcred_penalty_diagonal_error))
        self.setting_penalty_no_ad.setValue(int(config.kcred_penalty_no_ad_error))
        self.setting_xp_clean.setValue(int(config.xp_per_clean_hit))
        self.setting_xp_level.setValue(int(config.xp_per_level))

        self.setting_episode_timeout.setValue(float(config.episode_timeout))
        self.setting_click_cooldown.setValue(float(config.post_click_cooldown))
        self.setting_stationary_clean.setChecked(bool(config.stationary_click_counts_clean))
        self.setting_stationary_release.setValue(float(config.stationary_min_release_seconds))
        self.setting_require_release.setChecked(bool(config.require_release_at_click))

        input_settings = dict(config.input_timing or {})
        self.setting_input_enabled.setChecked(bool(input_settings.get("enabled", True)))
        self.setting_tap_max.setValue(float(input_settings.get("tap_max_seconds", 0.12)))
        self.setting_burst_max.setValue(float(input_settings.get("burst_max_seconds", 0.50)))
        self.setting_crouch_fire_max.setValue(float(input_settings.get("crouch_fire_max_seconds", 0.50)))

        calendar_settings = dict(config.training_calendar or {})
        self.setting_daily_goal.setValue(float(calendar_settings.get("daily_goal_hours", 2.0)))
        self.setting_light_day.setValue(float(calendar_settings.get("light_day_hours", 0.5)))
        self.setting_medium_day.setValue(float(calendar_settings.get("medium_day_hours", 1.0)))
        self.setting_strong_day.setValue(float(calendar_settings.get("strong_day_hours", 2.0)))

        tracker_settings = dict(config.tracker or {})
        self.setting_riot_name.setText(str(tracker_settings.get("riot_name", "")))
        self.setting_riot_tag.setText(str(tracker_settings.get("riot_tag", "")))
        self.setting_region.setText(str(tracker_settings.get("region", "br")))
        self.setting_platform.setText(str(tracker_settings.get("platform", "pc")))
        self.setting_api_key.setText(str(tracker_settings.get("api_key", "")))
        self.setting_show_api_key.setChecked(False)
        self.toggle_api_key_visibility(False)
        self.refresh_api_key_status()
        self.setting_import_limit.setValue(int(tracker_settings.get("import_limit", 20)))
        self.setting_max_scan.setValue(int(tracker_settings.get("max_scan_matches", 2500)))
        self.setting_request_delay.setValue(float(tracker_settings.get("request_delay_seconds", 1.5)))
        self.setting_ranked_detail_enrichment.setChecked(bool(tracker_settings.get("ranked_detail_enrichment", True)))

    def build_config_from_form(self) -> AppConfig:
        current = load_config()

        tracker_settings = dict(current.tracker or {})
        tracker_settings.update({
            "riot_name": self.setting_riot_name.text().strip(),
            "riot_tag": self.setting_riot_tag.text().strip(),
            "region": self.setting_region.text().strip() or "br",
            "platform": self.setting_platform.text().strip() or "pc",
            "api_key": self.setting_api_key.text().strip(),
            "import_limit": self.setting_import_limit.value(),
            "max_scan_matches": self.setting_max_scan.value(),
            "request_delay_seconds": self.setting_request_delay.value(),
            "ranked_detail_enrichment": self.setting_ranked_detail_enrichment.isChecked(),
        })

        calendar_settings = dict(current.training_calendar or {})
        calendar_settings.update({
            "daily_goal_hours": self.setting_daily_goal.value(),
            "light_day_hours": self.setting_light_day.value(),
            "medium_day_hours": self.setting_medium_day.value(),
            "strong_day_hours": self.setting_strong_day.value(),
        })

        input_settings = dict(current.input_timing or {})
        input_settings.update({
            "enabled": self.setting_input_enabled.isChecked(),
            "tap_max_seconds": self.setting_tap_max.value(),
            "burst_max_seconds": self.setting_burst_max.value(),
            "crouch_fire_max_seconds": self.setting_crouch_fire_max.value(),
        })

        return AppConfig.from_dict({
            "episode_timeout": self.setting_episode_timeout.value(),
            "post_click_cooldown": self.setting_click_cooldown.value(),
            "require_release_at_click": self.setting_require_release.isChecked(),
            "kcred_per_clean_hit": self.setting_kcred_clean.value(),
            "kcred_penalty_brake_error": self.setting_penalty_brake.value(),
            "kcred_penalty_diagonal_error": self.setting_penalty_diagonal.value(),
            "kcred_penalty_no_ad_error": self.setting_penalty_no_ad.value(),
            "stationary_click_counts_clean": self.setting_stationary_clean.isChecked(),
            "stationary_min_release_seconds": self.setting_stationary_release.value(),
            "xp_per_clean_hit": self.setting_xp_clean.value(),
            "xp_per_level": self.setting_xp_level.value(),
            "default_starting_balance": current.default_starting_balance,
            "default_next_weapon": current.default_next_weapon,
            "weapons": current.weapons,
            "tracker": tracker_settings,
            "training_calendar": calendar_settings,
            "input_timing": input_settings,
        })

    def save_quick_settings(self) -> None:
        if self.controller.is_session_active or self.controller.has_pending_purchase:
            QMessageBox.warning(
                self,
                "Configurações bloqueadas",
                "Finalize a sessão e a compra pendente antes de salvar configurações.",
            )
            return

        config = self.build_config_from_form()
        save_config(config)
        self.app_config = load_config()
        self.calendar_settings = self.app_config.training_calendar
        self.controller = AppController()
        self.refresh_api_key_status()
        self.refresh_all()
        self.settings_status_label.setText("Configurações salvas e recarregadas.")
        QMessageBox.information(
            self,
            "Configurações salvas",
            "As configurações foram salvas. Regras de protocolo e input timing passam a valer nas próximas sessões.",
        )

    def reload_quick_settings(self) -> None:
        self.app_config = load_config()
        self.calendar_settings = self.app_config.training_calendar
        self.load_settings_into_form(self.app_config)
        self.refresh_api_key_status()
        self.refresh_training_calendar_table()
        self.settings_status_label.setText("Configurações recarregadas do arquivo.")

    def reset_quick_settings_to_defaults(self) -> None:
        default_config = AppConfig()
        self.load_settings_into_form(default_config)
        self.settings_status_label.setText("Padrões carregados na tela. Clique em salvar para aplicar.")

    # ------------------------------------------------------------------
    # Listener setup
    # ------------------------------------------------------------------

    @staticmethod
    def get_key_name(key) -> str:
        try:
            return key.char.lower()
        except AttributeError:
            return str(key)

    def _start_input_listeners(self) -> None:
        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self.mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )

        self.keyboard_listener.start()
        self.mouse_listener.start()

    def _on_key_press(self, key):
        if key == keyboard.Key.f10:
            self.signals.toggle_session_requested.emit()
            return
        if key == keyboard.Key.f9:
            self.signals.reset_requested.emit()
            return
        if key == keyboard.Key.f6:
            self.signals.refresh_requested.emit()
            return
        if key == keyboard.Key.f12:
            self.signals.shutdown_requested.emit()
            return False
        self.controller.handle_key_press(self.get_key_name(key))

    def _on_key_release(self, key):
        self.controller.handle_key_release(self.get_key_name(key))

    def _on_click(self, x, y, button, pressed):
        button_name = InputTimingTracker.mouse_button_to_input_id(button)
        self.controller.handle_mouse_button(button_name, bool(pressed))

    def _on_scroll(self, x, y, dx, dy):
        if dy > 0:
            self.controller.handle_mouse_scroll("scroll_up")
        elif dy < 0:
            self.controller.handle_mouse_scroll("scroll_down")

    # ------------------------------------------------------------------
    # Session actions
    # ------------------------------------------------------------------

    def toggle_session(self) -> None:
        if self.controller.is_session_active:
            self.finish_session()
        else:
            self.start_session()

    def start_session(self) -> None:
        if self.controller.has_pending_purchase:
            QMessageBox.information(self, "Compra pendente", "Confirme a arma do próximo DM antes de iniciar outra sessão.")
            return
        start_data = self.controller.start_session(self.selected_session_mode())
        self.current_weapon_label.setText(f"Arma da sessão: {start_data['weapon']}")
        self.refresh_live_stats()
        self.refresh_buttons()

    def finish_session(self) -> None:
        if not self.controller.is_session_active:
            return
        result = self.controller.finish_session()
        if result.session_mode == "deathmatch":
            self.populate_weapon_combo()
        self.refresh_all()

    def reset_counters(self) -> None:
        self.controller.reset_counters()
        self.refresh_live_stats()

    def confirm_purchase(self) -> None:
        if self.controller.last_finished_session is None:
            return
        weapon_name = str(self.weapon_combo.currentData() or "")
        try:
            self.controller.confirm_purchase_by_name(weapon_name)
        except (RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "Compra não realizada", str(error))
            return
        self.refresh_all()

    def selected_session_mode(self) -> str:
        return str(self.session_mode_combo.currentData() or "deathmatch")

    def change_session_mode(self) -> None:
        session_mode = self.selected_session_mode()
        try:
            self.controller.set_session_mode(session_mode)
        except RuntimeError as error:
            QMessageBox.warning(self, "Modo bloqueado", str(error))
            self.set_session_mode_combo(self.controller.current_session_mode)
            return

        self.refresh_live_stats()
        self.refresh_buttons()

    def set_session_mode_combo(self, session_mode: str) -> None:
        index = self.session_mode_combo.findData(session_mode)
        if index < 0 or index == self.session_mode_combo.currentIndex():
            return

        self.session_mode_combo.blockSignals(True)
        self.session_mode_combo.setCurrentIndex(index)
        self.session_mode_combo.blockSignals(False)

    def import_tracker_deathmatches(self) -> None:
        import_all = self.import_all_tracker_checkbox.isChecked()
        self.run_tracker_import(import_all=import_all)

    def import_tracker_selected_day(self) -> None:
        selected = self.import_from_date.date().toString("yyyy-MM-dd")
        self.import_to_date.setDate(self.import_from_date.date())
        self.run_tracker_import(
            import_all=True,
            start_date=selected,
            end_date=selected,
            replace_date_range=True,
        )

    def import_tracker_selected_range(self) -> None:
        start_date = self.import_from_date.date().toString("yyyy-MM-dd")
        end_date = self.import_to_date.date().toString("yyyy-MM-dd")
        if end_date < start_date:
            QMessageBox.warning(self, "Intervalo inválido", "A data final não pode ser menor que a data inicial.")
            return
        self.run_tracker_import(
            import_all=True,
            start_date=start_date,
            end_date=end_date,
            replace_date_range=True,
        )

    def set_tracker_import_controls_enabled(self, enabled: bool) -> None:
        self.import_tracker_button.setEnabled(enabled)
        self.import_day_button.setEnabled(enabled)
        self.import_range_button.setEnabled(enabled)
        self.import_all_tracker_checkbox.setEnabled(enabled)
        self.import_from_date.setEnabled(enabled)
        self.import_to_date.setEnabled(enabled)

    def run_tracker_import(
        self,
        import_all: bool = False,
        start_date=None,
        end_date=None,
        replace_date_range: bool = False,
    ) -> None:
        self.set_tracker_import_controls_enabled(False)
        self.set_tracker_progress(0.0, "Tracker: importando")

        def on_progress(progress: dict) -> None:
            percent = float(progress.get("percent", 0.0))
            self.set_tracker_progress(percent, "Tracker: importando")
            QApplication.processEvents()

        try:
            result = self.controller.import_tracker_deathmatches(
                import_all=import_all,
                progress_callback=on_progress,
                start_date=start_date,
                end_date=end_date,
                replace_date_range=replace_date_range,
            )
        except Exception as error:
            QMessageBox.warning(self, "Importação falhou", str(error))
            self.set_tracker_progress(0.0, "Tracker: falhou")
        else:
            self.set_tracker_progress(result.percent, "Tracker: concluído")
            if result.message:
                QMessageBox.information(self, "Importação", result.message)
            self.refresh_all()
        finally:
            self.set_tracker_import_controls_enabled(True)

    def import_tracker_rankeds(self) -> None:
        import_all = self.import_all_ranked_checkbox.isChecked()
        self.run_ranked_import(import_all=import_all)

    def import_ranked_selected_day(self) -> None:
        selected = self.ranked_from_date.date().toString("yyyy-MM-dd")
        self.ranked_to_date.setDate(self.ranked_from_date.date())
        self.run_ranked_import(
            import_all=True,
            start_date=selected,
            end_date=selected,
            replace_date_range=True,
        )

    def import_ranked_selected_range(self) -> None:
        start_date = self.ranked_from_date.date().toString("yyyy-MM-dd")
        end_date = self.ranked_to_date.date().toString("yyyy-MM-dd")
        if end_date < start_date:
            QMessageBox.warning(self, "Intervalo inválido", "A data final não pode ser menor que a data inicial.")
            return
        self.run_ranked_import(
            import_all=True,
            start_date=start_date,
            end_date=end_date,
            replace_date_range=True,
        )

    def set_ranked_import_controls_enabled(self, enabled: bool) -> None:
        self.import_ranked_button.setEnabled(enabled)
        self.import_ranked_day_button.setEnabled(enabled)
        self.import_ranked_range_button.setEnabled(enabled)
        self.import_all_ranked_checkbox.setEnabled(enabled)
        self.ranked_from_date.setEnabled(enabled)
        self.ranked_to_date.setEnabled(enabled)

    def run_ranked_import(
        self,
        import_all: bool = False,
        start_date=None,
        end_date=None,
        replace_date_range: bool = False,
    ) -> None:
        self.set_ranked_import_controls_enabled(False)
        self.set_tracker_progress(0.0, "Ranked: importando")

        def on_progress(progress: dict) -> None:
            percent = float(progress.get("percent", 0.0))
            self.set_tracker_progress(percent, "Ranked: importando")
            QApplication.processEvents()

        try:
            result = self.controller.import_tracker_rankeds(
                import_all=import_all,
                progress_callback=on_progress,
                start_date=start_date,
                end_date=end_date,
                replace_date_range=replace_date_range,
            )
        except Exception as error:
            QMessageBox.warning(self, "Importação ranked falhou", str(error))
            self.set_tracker_progress(0.0, "Ranked: falhou")
        else:
            self.set_tracker_progress(result.percent, "Ranked: concluído")
            if result.message:
                QMessageBox.information(self, "Importação Ranked", result.message)
            self.refresh_all()
        finally:
            self.set_ranked_import_controls_enabled(True)

    # ------------------------------------------------------------------
    # Refresh/render
    # ------------------------------------------------------------------

    def set_tracker_progress(self, percent: float, label: str) -> None:
        value = int(max(0.0, min(percent, 100.0)) * 10)
        self.info_tracker_label.setText(label)
        self.info_tracker_progress_bar.setValue(value)
        self.info_tracker_progress_bar.setFormat(f"{percent:.1f}%")

    def populate_weapon_combo(self) -> None:
        self.weapon_combo.clear()
        for item in self.controller.get_available_weapons():
            badges = []
            if item.get("owned"):
                badges.append("ARS")
            if item.get("selected_next"):
                badges.append("NEXT")
            suffix = f" [{'/'.join(badges)}]" if badges else ""
            label = f"{item['name']} | {item['cost']} KC{suffix}"
            self.weapon_combo.addItem(label, item["name"])
            if not item.get("available"):
                index = self.weapon_combo.count() - 1
                model_item = self.weapon_combo.model().item(index)
                if model_item is not None:
                    model_item.setEnabled(False)

    def refresh_runtime_state(self) -> None:
        self.refresh_live_stats()
        self.refresh_buttons()

    def refresh_buttons(self) -> None:
        is_active = self.controller.is_session_active
        has_pending_purchase = self.controller.has_pending_purchase
        self.status_label.setText("Status: LIGADO" if is_active else "Status: DESLIGADO")
        self.start_button.setEnabled((not is_active) and (not has_pending_purchase))
        self.finish_button.setEnabled(is_active)
        self.reset_button.setEnabled(is_active)
        self.session_mode_combo.setEnabled((not is_active) and (not has_pending_purchase))
        self.weapon_combo.setEnabled(has_pending_purchase)
        self.confirm_purchase_button.setEnabled(has_pending_purchase)
        self.set_session_mode_combo(self.controller.current_session_mode)
        if is_active:
            if self.controller.current_session_mode == "ranked":
                self.purchase_status_label.setText("Sessão Ranked em andamento. Auditoria ativa, Coins desativadas.")
            else:
                self.purchase_status_label.setText("Sessão em andamento.")
        elif has_pending_purchase:
            self.purchase_status_label.setText("Escolha a arma do próximo DM.")
        else:
            if self.controller.current_session_mode == "ranked":
                self.purchase_status_label.setText("Pronto para iniciar Ranked com auditoria local.")
            else:
                self.purchase_status_label.setText("Pronto para iniciar o próximo DM.")

    def refresh_all(self) -> None:
        self.refresh_dashboard()
        self.refresh_live_stats()
        self.refresh_buttons()
        self.refresh_tracker_table()
        self.refresh_ranked_tab()
        self.refresh_training_calendar_table()

    def refresh_dashboard(self) -> None:
        stats = self.controller.get_dashboard()
        self.render_dashboard(stats)

    def render_dashboard(self, stats: DashboardStats) -> None:
        self.level_label.setText(f"Nível: {stats.progress.level}")
        self.xp_label.setText(f"XP: {stats.progress.current_level_xp}/{stats.progress.next_level_xp} | total {stats.progress.total_xp}")
        self.xp_bar.setValue(int(stats.progress.progress_rate * 10))
        self.xp_bar.setFormat(f"{stats.progress.progress_rate:.1f}%")
        self.balance_label.setText(f"Saldo: {stats.balance} KCreds")
        self.next_weapon_label.setText(f"Próxima arma: {stats.next_weapon}")
        self.total_sessions_label.setText(f"Sessões totais: {stats.total_sessions}")
        self.avg_rate_label.setText(f"Taxa média geral: {stats.average_protocol_rate:.1f}%")
        self.best_weapon_label.setText(f"Melhor arma: {stats.best_weapon} ({stats.best_weapon_rate:.1f}%)" if stats.best_weapon else "Melhor arma: -")
        self.today_label.setText(f"Hoje: {stats.today.sessions} sessões | {stats.today.average_protocol_rate:.1f}% | +{stats.today.kcreds_earned} KCred")

        self.tracker_total_label.setText(f"DMs importados: {stats.tracker.total_matches}")
        self.tracker_kd_label.setText(f"KD médio: {stats.tracker.average_kd:.2f}")
        self.tracker_best_map_label.setText(f"Melhor mapa: {stats.tracker.best_map} ({stats.tracker.best_map_kd:.2f} KD)" if stats.tracker.best_map else "Melhor mapa: -")
        self.tracker_best_agent_label.setText(f"Melhor agente: {stats.tracker.best_agent} ({stats.tracker.best_agent_kd:.2f} KD)" if stats.tracker.best_agent else "Melhor agente: -")

        if stats.tracker.best_match is not None:
            best = stats.tracker.best_match
            self.tracker_best_match_label.setText(f"Melhor DM: {best.map_name} | {best.kills}/{best.deaths}/{best.assists} | {best.kd:.2f} KD")
        else:
            self.tracker_best_match_label.setText("Melhor DM: -")

        if stats.tracker.last_match is not None:
            last = stats.tracker.last_match
            self.tracker_last_match_label.setText(f"Último DM: {last.date[:10]} | {last.map_name} | {last.agent} | {last.kills}/{last.deaths}/{last.assists}")
        else:
            self.tracker_last_match_label.setText("Último DM: -")

    def refresh_tracker_table(self) -> None:
        matches = load_tracker_dm_matches()[:150]
        headers = ["Data", "Mapa", "Agente", "K", "D", "A", "KD", "Duração", "Arma", "Protocolo"]

        self.tracker_table.setColumnCount(len(headers))
        self.tracker_table.setHorizontalHeaderLabels(headers)
        self.tracker_table.setRowCount(len(matches))

        for row, match in enumerate(matches):
            session_text = match.linked_weapon or "-"
            protocol_text = f"{match.linked_protocol_rate:.1f}%" if match.linked_session_id > 0 else "-"
            values = [
                match.date[:19],
                match.map_name,
                match.agent,
                match.kills,
                match.deaths,
                match.assists,
                f"{match.kd:.2f}",
                match.duration or "-",
                session_text,
                protocol_text,
            ]

            for col, value in enumerate(values):
                self.tracker_table.setItem(row, col, QTableWidgetItem(str(value)))
        self.tracker_table.resizeColumnsToContents()

    def refresh_ranked_tab(self) -> None:
        stats = build_ranked_radiante_stats()
        self.ranked_total_label.setText(f"Rankeds analisadas: {stats.total_matches}")
        self.ranked_winrate_label.setText(f"Winrate: {stats.winrate:.1f}% ({stats.wins}V/{stats.losses}D)")
        self.ranked_rr_label.setText(f"RR total: {stats.total_rr_change:+d} | média {stats.average_rr_change:+.1f}")
        self.ranked_acs_label.setText(f"ACS médio: {stats.average_acs:.1f}")
        self.ranked_adr_label.setText(f"ADR médio: {stats.average_adr:.1f}")
        self.ranked_kast_label.setText(f"KAST médio: {stats.average_kast:.1f}%" if stats.average_kast else "KAST médio: -")
        self.ranked_dd_label.setText(f"DDΔ total: {stats.total_damage_delta:+d} | DD/R {stats.average_dd_per_round:+.1f}")
        self.ranked_fbfd_label.setText(f"FB {stats.total_first_kills} / FD {stats.total_first_deaths} | Δ {stats.fb_fd_delta:+d}")
        self.ranked_best_map_label.setText(f"Melhor mapa: {stats.best_map} ({stats.best_map_winrate:.1f}%)" if stats.best_map else "Melhor mapa: -")
        self.ranked_worst_map_label.setText(f"Pior mapa: {stats.worst_map} ({stats.worst_map_winrate:.1f}%)" if stats.worst_map else "Pior mapa: -")
        self.ranked_signal_label.setText(f"Sinal dominante: {stats.dominant_signal or '-'}")
        self.ranked_focus_label.setText(f"Foco recomendado: {stats.next_focus or '-'}")

        matches = load_tracker_ranked_matches()[:150]
        headers = ["Data", "Mapa", "Agente", "Resultado", "Rank", "RRΔ", "ACS", "ADR", "DDΔ", "DD/R", "FB", "FD", "FB-FD", "K/D/A"]
        self.ranked_table.setColumnCount(len(headers))
        self.ranked_table.setHorizontalHeaderLabels(headers)
        self.ranked_table.setRowCount(len(matches))

        for row, match in enumerate(matches):
            values = [
                match.date[:19],
                match.map_name,
                match.agent,
                match.result or "-",
                match.rank or "-",
                f"{match.rr_change:+d}" if match.rr_change else "-",
                f"{match.acs:.1f}" if match.acs else "-",
                f"{match.adr:.1f}" if match.adr else "-",
                f"{match.damage_delta:+d}",
                f"{match.dd_per_round:+.1f}" if match.dd_per_round else "-",
                match.first_kills,
                match.first_deaths,
                f"{match.fb_fd_delta:+d}",
                f"{match.kills}/{match.deaths}/{match.assists}",
            ]
            for col, value in enumerate(values):
                self.ranked_table.setItem(row, col, QTableWidgetItem(str(value)))
        self.ranked_table.resizeColumnsToContents()

    def refresh_training_calendar_table(self) -> None:
        days = build_training_calendar()
        day_by_date = {day.date: day for day in days}
        self.render_training_calendar_grid(day_by_date)
        self.render_training_days_summary(days[:90])

    def render_training_calendar_grid(self, day_by_date: dict) -> None:
        year = self.current_calendar_month.year
        month = self.current_calendar_month.month
        month_name = self.get_month_name_pt(month)
        self.calendar_month_label.setText(f"{month_name} {year}")

        monthly_days = [
            day for key, day in day_by_date.items()
            if key.startswith(f"{year:04d}-{month:02d}")
        ]
        monthly_hours = sum(day.total_hours for day in monthly_days)
        monthly_seconds = sum(day.total_seconds for day in monthly_days)
        monthly_dms = sum(day.dm_count for day in monthly_days)
        active_days = len([day for day in monthly_days if day.dm_count > 0])
        goal_hours = self.get_daily_goal_hours()
        goal_days = len([day for day in monthly_days if day.total_hours >= goal_hours])
        average_hours = (monthly_hours / active_days) if active_days > 0 else 0.0
        self.calendar_month_summary_label.setText(
            f"Resumo do mês: {monthly_dms} DMs | {self.format_duration(monthly_seconds)} | "
            f"{active_days} dias ativos | média {average_hours:.2f}h/dia ativo"
        )
        self.calendar_goal_label.setText(
            f"Meta diária: {goal_hours:.2f}h | dias batendo meta: {goal_days}/{active_days}"
        )

        month_weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
        while len(month_weeks) < 6:
            last_week = month_weeks[-1]
            next_start = last_week[-1].toordinal() + 1
            month_weeks.append([date.fromordinal(next_start + index) for index in range(7)])

        for row in range(6):
            self.training_calendar_table.setRowHeight(row, 58)
            for col in range(7):
                current_day = month_weeks[row][col]
                day_key = current_day.isoformat()
                stats = day_by_date.get(day_key)
                item = QTableWidgetItem(self.format_calendar_cell(current_day, stats))
                item.setTextAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                item.setToolTip(self.format_calendar_tooltip(current_day, stats))

                background = self.get_calendar_background(stats.total_hours if stats else 0.0)
                foreground = QColor("#111827") if current_day.month == month else QColor("#6B7280")
                item.setBackground(QBrush(background))
                item.setForeground(QBrush(foreground))

                self.training_calendar_table.setItem(row, col, item)

        self.training_calendar_table.resizeColumnsToContents()

    def render_training_days_summary(self, days: list) -> None:
        self.training_days_summary_table.setRowCount(len(days))

        for row, day in enumerate(days):
            hours_text = f"{day.total_hours:.2f}h"
            time_text = self.format_duration(day.total_seconds)
            values = [
                day.date,
                day.dm_count,
                time_text,
                hours_text,
                f"{day.average_kd:.2f}",
                day.linked_sessions,
                day.weapons or "-",
            ]
            for col, value in enumerate(values):
                self.training_days_summary_table.setItem(row, col, QTableWidgetItem(str(value)))
        self.training_days_summary_table.resizeColumnsToContents()

    def show_previous_month(self) -> None:
        year = self.current_calendar_month.year
        month = self.current_calendar_month.month - 1
        if month < 1:
            month = 12
            year -= 1
        self.current_calendar_month = date(year, month, 1)
        self.refresh_training_calendar_table()

    def show_next_month(self) -> None:
        year = self.current_calendar_month.year
        month = self.current_calendar_month.month + 1
        if month > 12:
            month = 1
            year += 1
        self.current_calendar_month = date(year, month, 1)
        self.refresh_training_calendar_table()

    def show_current_month(self) -> None:
        self.current_calendar_month = date.today().replace(day=1)
        self.refresh_training_calendar_table()

    @staticmethod
    def get_month_name_pt(month: int) -> str:
        names = {
            1: "Janeiro",
            2: "Fevereiro",
            3: "Março",
            4: "Abril",
            5: "Maio",
            6: "Junho",
            7: "Julho",
            8: "Agosto",
            9: "Setembro",
            10: "Outubro",
            11: "Novembro",
            12: "Dezembro",
        }
        return names.get(month, str(month))

    @staticmethod
    def format_calendar_cell(current_day: date, stats) -> str:
        if stats is None or stats.dm_count <= 0:
            return f"{current_day.day}\n—"
        return (
            f"{current_day.day}\n"
            f"{stats.total_hours:.2f}h\n"
            f"{stats.dm_count} DM"
        )

    def format_calendar_tooltip(self, current_day: date, stats) -> str:
        if stats is None or stats.dm_count <= 0:
            return f"{current_day.isoformat()}\nSem treino importado."
        return (
            f"{current_day.isoformat()}\n"
            f"Tempo de treino: {self.format_duration(stats.total_seconds)}\n"
            f"DMs: {stats.dm_count}\n"
            f"KD médio: {stats.average_kd:.2f}\n"
            f"Sessões vinculadas: {stats.linked_sessions}\n"
            f"Armas: {stats.weapons or '-'}"
        )

    def get_daily_goal_hours(self) -> float:
        return float(self.calendar_settings.get("daily_goal_hours", 2.0))

    def get_calendar_legend_text(self) -> str:
        light = float(self.calendar_settings.get("light_day_hours", 0.5))
        medium = float(self.calendar_settings.get("medium_day_hours", 1.0))
        strong = float(self.calendar_settings.get("strong_day_hours", 2.0))
        goal = self.get_daily_goal_hours()
        return (
            "Legenda: cinza = sem treino | "
            f"azul claro < {light:.1f}h | azul médio ≥ {medium:.1f}h | "
            f"azul forte ≥ {strong:.1f}h | verde ≥ meta {goal:.1f}h"
        )

    def get_calendar_background(self, hours: float) -> QColor:
        light = float(self.calendar_settings.get("light_day_hours", 0.5))
        medium = float(self.calendar_settings.get("medium_day_hours", 1.0))
        strong = float(self.calendar_settings.get("strong_day_hours", 2.0))
        goal = self.get_daily_goal_hours()

        if hours <= 0:
            return QColor("#F3F4F6")
        if hours >= goal:
            return QColor("#86EFAC")
        if hours >= strong:
            return QColor("#60A5FA")
        if hours >= medium:
            return QColor("#93C5FD")
        if hours >= light:
            return QColor("#BFDBFE")
        return QColor("#DBEAFE")

    def export_current_month_calendar(self) -> None:
        days = build_training_calendar()
        year = self.current_calendar_month.year
        month = self.current_calendar_month.month
        monthly_days = [day for day in days if day.date.startswith(f"{year:04d}-{month:02d}")]

        default_name = str(self.calendar_settings.get("export_filename") or "training_calendar_month.csv")
        default_path = DATA_DIR / default_name
        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar calendário do mês",
            str(default_path),
            "CSV (*.csv)",
        )

        if not selected_path:
            return

        import csv

        with open(selected_path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow([
                "date",
                "dm_count",
                "total_time",
                "total_hours",
                "average_kd",
                "linked_sessions",
                "average_protocol_rate",
                "weapons",
                "goal_met",
            ])
            goal_hours = self.get_daily_goal_hours()
            for day in monthly_days:
                writer.writerow([
                    day.date,
                    day.dm_count,
                    self.format_duration(day.total_seconds),
                    f"{day.total_hours:.2f}",
                    f"{day.average_kd:.2f}",
                    day.linked_sessions,
                    f"{day.average_protocol_rate:.1f}",
                    day.weapons,
                    "sim" if day.total_hours >= goal_hours else "não",
                ])

        QMessageBox.information(self, "Calendário exportado", f"Arquivo salvo em:\n{selected_path}")

    @staticmethod
    def format_duration(seconds: int) -> str:
        seconds = max(int(seconds), 0)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        remaining_seconds = seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"
        return f"{minutes:02d}:{remaining_seconds:02d}"

    def refresh_live_stats(self) -> None:
        stats = self.controller.live_stats
        self.clean_hits_label.setText(f"Acertos limpos: {stats.clean_hits}")
        self.brake_errors_label.setText(f"Erros de freio: {stats.brake_errors}")
        self.diagonal_errors_label.setText(f"Erros de diagonal: {stats.diagonal_errors}")
        self.no_ad_errors_label.setText("Sem A/D (legado): desativado")
        self.valid_attempts_label.setText(f"Tentativas válidas: {stats.valid_attempts}")
        self.ignored_clicks_label.setText(f"Cliques ignorados: {stats.ignored_clicks}")
        self.current_rate_label.setText(f"Taxa atual: {stats.protocol_rate:.1f}%")
        if self.controller.current_session_mode == "ranked":
            self.current_kcred_label.setText("Coins nesta sessão: desativadas (Ranked)")
        else:
            self.current_kcred_label.setText(f"KCred desta sessão: +{self.controller.current_session_kcreds}")

        input_stats = self.controller.live_input_stats
        self.fire_profile_label.setText(
            f"Tiro: tap {input_stats.fire_taps} | "
            f"burst {input_stats.fire_bursts} | "
            f"spray longo {input_stats.fire_long_sprays}"
        )
        self.fire_duration_label.setText(
            f"Duração tiro: média {input_stats.average_fire_seconds:.2f}s | "
            f"máx {input_stats.max_fire_seconds:.2f}s"
        )
        self.fire_context_label.setText(
            f"Tiro W/S: {input_stats.shots_while_forward} | "
            f"crouch+tiro: {input_stats.shots_with_crouch} | "
            f"crouch longo: {input_stats.crouch_fire_long_count}"
        )
        self.input_motion_label.setText(
            f"Diagonal: {input_stats.diagonal_entries}x | "
            f"{input_stats.diagonal_seconds:.2f}s"
        )
        self.input_actions_label.setText(
            f"Inputs: teclas {input_stats.key_presses} | "
            f"mouse {input_stats.mouse_presses} | "
            f"scroll {input_stats.scroll_events} | "
            f"scroll jump {input_stats.scroll_jump_events}"
        )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self.controller.is_session_active:
            self.controller.stop_without_saving()
        if self.mouse_listener is not None and self.mouse_listener.running:
            self.mouse_listener.stop()
        if self.keyboard_listener is not None and self.keyboard_listener.running:
            self.keyboard_listener.stop()
        event.accept()
