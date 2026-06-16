from __future__ import annotations

import calendar
import ctypes
import json
import os
import sys
from collections import Counter
from datetime import date, datetime

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
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.app_controller import AppController
from core.input_timing import InputTimingTracker
from core.config import CONFIG_FILE, DATA_DIR, PROJECT_ROOT, AppConfig, load_config, save_config
from core.dashboard import DashboardStats
from core.modules import FUTURE_MODULES
from core.persistence import load_all_sessions
from core.protocol_tracker import DIAGONAL_RULE_LABELS
from core.runtime_identity import collect_runtime_identity
from core.tracker_importer import (
    build_ranked_radiante_stats,
    build_training_calendar,
    get_tracker_settings,
    load_tracker_dm_matches,
    load_tracker_ranked_matches,
)
from ui.screens.history_screen import HistoryScreen
from ui.screens.inventory_screen import InventoryScreen, WeaponButton
from ui.overlay_window import OverlayWindow


class GuiSignals(QObject):
    toggle_session_requested = Signal()
    reset_requested = Signal()
    refresh_requested = Signal()
    shutdown_requested = Signal()


class MainWindow(QWidget):
    LIVE_UPDATE_INTERVAL_MS = 400
    ACTIVE_SESSION_UPDATE_INTERVAL_MS = 1000
    APP_VERSION = "v0.22.6"

    def __init__(self) -> None:
        super().__init__()

        self.controller = AppController()
        self.signals = GuiSignals()
        self.keyboard_listener = None
        self.mouse_listener = None
        self.last_runtime_revision = -1
        self.setWindowTitle(f"MVP APP {self.APP_VERSION} - Valorant Training / Coins")
        self.resize(1180, 820)
        self.setMinimumSize(980, 680)
        self.current_calendar_month = date.today().replace(day=1)
        self.app_config = load_config()
        self.calendar_settings = self.app_config.training_calendar
        self.weapon_selection_counts: dict[str, int] = {}

        self._build_ui()
        self.overlay_window = OverlayWindow(
            self.controller.get_overlay_snapshot,
            self.save_overlay_position,
        )
        self._connect_signals()
        self.load_settings_into_form(self.app_config)
        self.refresh_runtime_identity()
        self.refresh_input_debug_view()
        self.apply_overlay_settings()
        self._start_input_listeners()

        self.live_timer = QTimer(self)
        self.live_timer.timeout.connect(self.refresh_runtime_state)
        self.live_timer.start(self.LIVE_UPDATE_INTERVAL_MS)

        self.refresh_all()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_main_menu(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(150)
        panel.setMaximumWidth(190)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(6)
        layout.addWidget(QLabel("Main Menu"))

        self.main_menu_buttons: dict[str, QPushButton] = {}
        for key, label in [
            ("game_modes", "Game Modes"),
            ("inventory", "Inventory"),
            ("history", "History"),
            ("settings", "Settings"),
        ]:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(44)
            button.clicked.connect(lambda checked=False, page_key=key: self.show_main_page(page_key))
            self.main_menu_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        return panel

    def _build_main_content_stack(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        self.main_stack = QStackedWidget()
        self.main_pages = {
            "game_modes": self._build_game_modes_shell(),
            "inventory": self._build_inventory_shell(),
            "history": self._build_history_shell(),
            "settings": self._build_settings_shell(),
        }
        self.main_page_order = ["game_modes", "inventory", "history", "settings"]
        for key in self.main_page_order:
            self.main_stack.addWidget(self.main_pages[key])
        layout.addWidget(self.main_stack)
        self.show_main_page("game_modes")
        return container

    def _build_section_shell(self, title: str, entries: list[tuple[str, QWidget]], attr_prefix: str) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addWidget(QLabel(title))

        buttons_layout = QHBoxLayout()
        stack = QStackedWidget()
        buttons: list[QPushButton] = []

        for index, (label, widget) in enumerate(entries):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(38)
            button.clicked.connect(
                lambda checked=False, stack_widget=stack, target=index, button_list=buttons: self._set_subpage(
                    stack_widget,
                    target,
                    button_list,
                )
            )
            buttons.append(button)
            buttons_layout.addWidget(button)
            stack.addWidget(widget)

        buttons_layout.addStretch(1)
        root.addLayout(buttons_layout)
        root.addWidget(stack, stretch=1)
        setattr(self, f"{attr_prefix}_stack", stack)
        setattr(self, f"{attr_prefix}_buttons", buttons)
        self._set_subpage(stack, 0, buttons)
        return page

    def _set_subpage(self, stack: QStackedWidget, index: int, buttons: list[QPushButton]) -> None:
        stack.setCurrentIndex(index)
        for button_index, button in enumerate(buttons):
            button.setChecked(button_index == index)

    def show_main_page(self, page_key: str) -> None:
        if page_key not in self.main_page_order:
            return
        index = self.main_page_order.index(page_key)
        self.main_stack.setCurrentIndex(index)
        for key, button in self.main_menu_buttons.items():
            button.setChecked(key == page_key)
        if page_key == "history":
            self._set_subpage(self.history_stack, 0, self.history_buttons)

    def _build_game_modes_shell(self) -> QWidget:
        page = self._build_section_shell(
            "Game Modes",
            [
                ("Deathmatch", self._build_dm_tab()),
                ("Ranked", self._build_ranked_audit_page()),
            ],
            "game_modes",
        )
        self.game_modes_buttons[0].clicked.connect(
            lambda _checked=False: self.select_game_mode("deathmatch")
        )
        self.game_modes_buttons[1].clicked.connect(
            lambda _checked=False: self.select_game_mode("ranked")
        )
        return page

    def _build_inventory_shell(self) -> QWidget:
        self.inventory_screen = InventoryScreen()
        self._bind_inventory_screen_widgets(self.inventory_screen)
        return self.inventory_screen

    def _build_history_shell(self) -> QWidget:
        self.history_screen = HistoryScreen()
        self._bind_history_screen_widgets(self.history_screen)
        return self.history_screen

    def _bind_inventory_screen_widgets(self, screen: InventoryScreen) -> None:
        self.inventory_stack = screen.inventory_stack
        self.inventory_buttons = screen.inventory_buttons
        self.balance_label = screen.balance_label
        self.today_label = screen.today_label
        self.coins_equipped_label = screen.coins_equipped_label
        self.coins_next_step_label = screen.coins_next_step_label
        self.inventory_hint_label = screen.inventory_hint_label
        self.weapons_equipped_label = screen.weapons_equipped_label
        self.available_weapons_label = screen.available_weapons_label
        self.weapon_combo = screen.weapon_combo
        self.weapon_button_widgets = screen.weapon_button_widgets
        self.weapon_owned_labels = screen.weapon_owned_labels
        self.weapon_selected_labels = screen.weapon_selected_labels
        self.weapon_cost_labels = screen.weapon_cost_labels
        self.weapon_group_boxes = screen.weapon_group_boxes
        self.cart_summary_label = screen.cart_summary_label
        self.cart_total_label = screen.cart_total_label
        self.cart_balance_label = screen.cart_balance_label
        self.confirm_purchase_button = screen.confirm_purchase_button
        self.confirm_sell_button = screen.confirm_sell_button
        self.clear_selection_button = screen.clear_selection_button
        self.store_mode_combo = screen.store_mode_combo
        self.purchase_status_label = screen.purchase_status_label
        self.weapons_empty_label = screen.weapons_empty_label
        self.level_label = screen.level_label
        self.xp_label = screen.xp_label
        self.xp_bar = screen.xp_bar
        self.next_weapon_label = screen.next_weapon_label
        self.total_sessions_label = screen.total_sessions_label
        self.avg_rate_label = screen.avg_rate_label
        self.best_weapon_label = screen.best_weapon_label

    def _bind_history_screen_widgets(self, screen: HistoryScreen) -> None:
        self.history_stack = screen.history_stack
        self.history_buttons = screen.history_buttons
        self.tracker_page = screen.tracker_page
        self.prev_month_button = screen.prev_month_button
        self.calendar_month_label = screen.calendar_month_label
        self.today_month_button = screen.today_month_button
        self.next_month_button = screen.next_month_button
        self.calendar_month_summary_label = screen.calendar_month_summary_label
        self.calendar_goal_label = screen.calendar_goal_label
        self.training_calendar_table = screen.training_calendar_table
        self.calendar_legend_label = screen.calendar_legend_label
        self.import_tracker_button = screen.import_tracker_button
        self.import_all_tracker_checkbox = screen.import_all_tracker_checkbox
        self.import_day_button = screen.import_day_button
        self.import_range_button = screen.import_range_button
        self.import_from_date = screen.import_from_date
        self.import_to_date = screen.import_to_date
        self.tracker_total_label = screen.tracker_total_label
        self.tracker_kd_label = screen.tracker_kd_label
        self.tracker_best_map_label = screen.tracker_best_map_label
        self.tracker_best_agent_label = screen.tracker_best_agent_label
        self.tracker_best_match_label = screen.tracker_best_match_label
        self.tracker_last_match_label = screen.tracker_last_match_label
        self.tracker_status_label = screen.tracker_status_label
        self.tracker_table = screen.tracker_table
        self.training_sessions_summary_label = screen.training_sessions_summary_label
        self.training_sessions_status_label = screen.training_sessions_status_label
        self.training_sessions_table = screen.training_sessions_table
        self.import_ranked_button = screen.import_ranked_button
        self.import_all_ranked_checkbox = screen.import_all_ranked_checkbox
        self.import_ranked_day_button = screen.import_ranked_day_button
        self.import_ranked_range_button = screen.import_ranked_range_button
        self.ranked_from_date = screen.ranked_from_date
        self.ranked_to_date = screen.ranked_to_date
        self.ranked_total_label = screen.ranked_total_label
        self.ranked_winrate_label = screen.ranked_winrate_label
        self.ranked_rr_label = screen.ranked_rr_label
        self.ranked_acs_label = screen.ranked_acs_label
        self.ranked_adr_label = screen.ranked_adr_label
        self.ranked_dd_label = screen.ranked_dd_label
        self.ranked_fbfd_label = screen.ranked_fbfd_label
        self.ranked_kast_label = screen.ranked_kast_label
        self.ranked_signal_label = screen.ranked_signal_label
        self.ranked_focus_label = screen.ranked_focus_label
        self.ranked_best_map_label = screen.ranked_best_map_label
        self.ranked_worst_map_label = screen.ranked_worst_map_label
        self.ranked_history_status_label = screen.ranked_history_status_label
        self.ranked_table = screen.ranked_table
        self.hide_import_module_surfaces()

    def hide_import_module_surfaces(self) -> None:
        self.tracker_page.setVisible(False)
        if len(self.history_buttons) > 2:
            self.history_buttons[2].setVisible(False)
        if self.history_stack.count() > 2:
            self.history_stack.widget(2).setVisible(False)

    def _build_settings_shell(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addWidget(QLabel("Settings"))
        entries = [
            ("Input Settings", self._make_scroll_page(self._build_keys_input_settings_page())),
            ("Input Debug", self._make_scroll_page(self._build_input_debug_page())),
            ("Overlay", self._make_scroll_page(self._build_overlay_settings_page())),
            ("Modules / Extensions", self._make_scroll_page(self._build_modules_page())),
            ("Debug / Errors", self._make_scroll_page(self._build_debug_settings_page())),
            ("Runtime / About", self._make_scroll_page(self._build_runtime_identity_page())),
        ]

        buttons_layout = QHBoxLayout()
        self.settings_stack = QStackedWidget()
        self.settings_buttons: list[QPushButton] = []
        for index, (label, widget) in enumerate(entries):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(38)
            button.clicked.connect(
                lambda checked=False, target=index: self._set_subpage(
                    self.settings_stack,
                    target,
                    self.settings_buttons,
                )
            )
            self.settings_buttons.append(button)
            buttons_layout.addWidget(button)
            self.settings_stack.addWidget(widget)

        buttons_layout.addStretch(1)
        root.addLayout(buttons_layout)
        root.addWidget(self.settings_stack, stretch=1)

        actions = QHBoxLayout()
        self.reload_settings_button = QPushButton("Reload")
        self.reset_settings_button = QPushButton("Reset Screen Defaults")
        self.save_settings_button = QPushButton("Save Settings")
        self.settings_status_label = QLabel("Ready.")
        actions.addWidget(self.reload_settings_button)
        actions.addWidget(self.reset_settings_button)
        actions.addWidget(self.save_settings_button)
        actions.addWidget(self.settings_status_label, stretch=1)
        root.addLayout(actions)

        self._set_subpage(self.settings_stack, 0, self.settings_buttons)
        return page

    @staticmethod
    def _make_scroll_page(content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        return scroll

    def _build_live_session_group(self) -> QGroupBox:
        live_group = QGroupBox("Current Session")
        live_layout = QGridLayout(live_group)

        self.current_weapon_label = QLabel("Session weapon: -")
        self.clean_hits_label = QLabel("Clean hits: 0")
        self.brake_errors_label = QLabel("Counter-strafe errors: 0")
        self.diagonal_errors_label = QLabel("Diagonal errors: 0")
        self.no_ad_errors_label = QLabel("No A/D (legacy): disabled")
        self.valid_attempts_label = QLabel("Valid attempts: 0")
        self.ignored_clicks_label = QLabel("Ignored clicks: 0")
        self.current_rate_label = QLabel("Current rate: 0.0%")
        self.current_kcred_label = QLabel("Coins this session: +0")
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
        return live_group

    def _build_input_summary_group(self) -> QGroupBox:
        input_group = QGroupBox("Input Summary")
        input_layout = QGridLayout(input_group)
        self.fire_profile_label = QLabel("Fire: tap 0 | burst 0 | long spray 0")
        self.fire_duration_label = QLabel("Fire duration: avg 0.00s | max 0.00s")
        self.fire_context_label = QLabel("W/S shots: 0 | crouch+fire: 0 | long crouch fire: 0")
        self.input_motion_label = QLabel("Diagonal: 0x | 0.00s")
        self.input_actions_label = QLabel("Inputs: keys 0 | mouse 0 | scroll 0 | jump scroll 0")
        input_layout.addWidget(self.fire_profile_label, 0, 0, 1, 2)
        input_layout.addWidget(self.fire_duration_label, 1, 0, 1, 2)
        input_layout.addWidget(self.fire_context_label, 2, 0, 1, 2)
        input_layout.addWidget(self.input_motion_label, 3, 0)
        input_layout.addWidget(self.input_actions_label, 3, 1)
        return input_group

    def _build_protocol_debug_group(self) -> QGroupBox:
        debug_group = QGroupBox("Debug / Errors")
        debug_layout = QVBoxLayout(debug_group)
        self.protocol_rule_status_label = QLabel("Protocol rules: -")
        self.protocol_debug_text = QPlainTextEdit()
        self.protocol_debug_text.setReadOnly(True)
        self.protocol_debug_text.setMinimumHeight(180)
        self.audit_path_label = QLabel(f"Audit folder: {DATA_DIR / 'input_audit'}")
        debug_layout.addWidget(self.protocol_rule_status_label)
        debug_layout.addWidget(self.protocol_debug_text)
        debug_layout.addWidget(self.audit_path_label)
        return debug_group

    def _build_ranked_audit_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        info_group = QGroupBox("Ranked Audit")
        info_layout = QVBoxLayout(info_group)
        self.ranked_mode_info_label = QLabel(
            "Ranked sessions use the session controls above, record protocol events, and keep Coins disabled."
        )
        self.ranked_mode_info_label.setWordWrap(True)
        self.ranked_live_summary_label = QLabel("No ranked audit session is active.")
        info_layout.addWidget(self.ranked_mode_info_label)
        info_layout.addWidget(self.ranked_live_summary_label)
        root.addWidget(info_group)
        root.addStretch(1)
        return page

    def _build_keys_input_settings_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addWidget(QLabel("Keys / Input"))
        root.addWidget(self._build_protocol_settings_group())
        root.addWidget(self._build_input_settings_group())
        root.addStretch(1)
        return page

    def _build_import_settings_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addWidget(QLabel("Import"))
        root.addWidget(self._build_tracker_settings_group())
        root.addWidget(self._build_match_import_group("Deathmatch", ranked=False))
        root.addWidget(self._build_match_import_group("Ranked", ranked=True))
        calendar_group = QGroupBox("Training Calendar")
        calendar_layout = QGridLayout(calendar_group)
        self.import_training_calendar_button = QPushButton("Import Training Calendar CSV")
        self.export_training_calendar_button = QPushButton("Export Training Calendar CSV")
        calendar_note = QLabel("Use CSV tools here. The live History calendar still reflects local session and match data.")
        calendar_note.setWordWrap(True)
        calendar_layout.addWidget(self.import_training_calendar_button, 0, 0)
        calendar_layout.addWidget(self.export_training_calendar_button, 0, 1)
        calendar_layout.addWidget(calendar_note, 1, 0, 1, 2)
        calendar_layout.setColumnStretch(0, 1)
        calendar_layout.setColumnStretch(1, 1)
        root.addWidget(calendar_group)
        root.addStretch(1)
        return page

    def _build_match_import_group(self, title: str, ranked: bool) -> QGroupBox:
        group = QGroupBox(f"{title} Import")
        layout = QGridLayout(group)
        mode = QComboBox()
        mode.addItem("Update only", "update")
        mode.addItem("Import whole season", "season")
        mode.addItem("Import date range", "range")
        season = QComboBox()
        season.addItem("Current season", "current")
        if ranked:
            self.ranked_import_mode = mode
            self.ranked_season_selector = season
            action = self.import_ranked_button
            from_date = self.ranked_from_date
            to_date = self.ranked_to_date
        else:
            self.dm_import_mode = mode
            self.dm_season_selector = season
            action = self.import_tracker_button
            from_date = self.import_from_date
            to_date = self.import_to_date
        action.setText(f"Run {title} Import")
        layout.addWidget(QLabel("Mode:"), 0, 0)
        layout.addWidget(mode, 0, 1)
        layout.addWidget(QLabel("Season:"), 1, 0)
        layout.addWidget(season, 1, 1)
        layout.addWidget(QLabel("From:"), 2, 0)
        layout.addWidget(from_date, 2, 1)
        layout.addWidget(QLabel("To:"), 2, 2)
        layout.addWidget(to_date, 2, 3)
        layout.addWidget(action, 3, 0, 1, 2)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        mode.currentIndexChanged.connect(
            lambda _=0, is_ranked=ranked: self.refresh_import_mode(is_ranked)
        )
        self.refresh_import_mode(ranked)
        return group

    def _build_debug_settings_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addWidget(QLabel("Debug / Errors"))
        root.addWidget(self._build_protocol_debug_group())
        root.addStretch(1)
        return page

    def _build_input_debug_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addWidget(QLabel("Input Debug"))

        summary_group = QGroupBox("Live Input State")
        summary_layout = QGridLayout(summary_group)
        self.input_debug_body_state_label = QLabel("Body state: -")
        self.input_debug_active_keys_label = QLabel("Active keys: -")
        self.input_debug_last_fire_label = QLabel("Last fire state: -")
        self.input_debug_windows_label = QLabel("Jump: - | Brake: -")
        self.input_debug_overlay_label = QLabel("Overlay: -")
        self.input_debug_ratios_label = QLabel("Ratios: -")
        self.input_debug_ratios_label.setWordWrap(True)
        self.input_debug_warnings_label = QLabel("Warnings: -")
        self.input_debug_warnings_label.setWordWrap(True)
        summary_layout.addWidget(self.input_debug_body_state_label, 0, 0)
        summary_layout.addWidget(self.input_debug_active_keys_label, 0, 1)
        summary_layout.addWidget(self.input_debug_last_fire_label, 1, 0)
        summary_layout.addWidget(self.input_debug_windows_label, 1, 1)
        summary_layout.addWidget(self.input_debug_overlay_label, 2, 0, 1, 2)
        summary_layout.addWidget(self.input_debug_ratios_label, 3, 0, 1, 2)
        summary_layout.addWidget(self.input_debug_warnings_label, 4, 0, 1, 2)
        root.addWidget(summary_group)

        self.input_debug_text = QPlainTextEdit()
        self.input_debug_text.setReadOnly(True)
        self.input_debug_text.setMinimumHeight(320)
        root.addWidget(self.input_debug_text, stretch=1)

        actions = QHBoxLayout()
        self.refresh_input_debug_button = QPushButton("Refresh Input Debug")
        self.copy_input_debug_button = QPushButton("Copy Input Debug")
        self.save_input_debug_button = QPushButton("Save Input Debug Log")
        self.input_debug_copy_status_label = QLabel("Ready.")
        actions.addWidget(self.refresh_input_debug_button)
        actions.addWidget(self.copy_input_debug_button)
        actions.addWidget(self.save_input_debug_button)
        actions.addWidget(self.input_debug_copy_status_label, stretch=1)
        root.addLayout(actions)
        return page

    def _build_modules_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addWidget(QLabel("Modules / Extensions"))

        for app_module in FUTURE_MODULES:
            group = QGroupBox(app_module.name)
            layout = QGridLayout(group)
            status_label = QLabel(app_module.status)
            status_label.setObjectName("ModuleStatusLabel")
            description_label = QLabel(app_module.description)
            description_label.setWordWrap(True)
            layout.addWidget(QLabel("Status:"), 0, 0)
            layout.addWidget(status_label, 0, 1)
            layout.addWidget(description_label, 1, 0, 1, 2)
            group.setEnabled(False)
            root.addWidget(group)

        root.addStretch(1)
        return page

    def _build_runtime_identity_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addWidget(QLabel("Runtime / Diagnostics / About"))

        warning_group = QGroupBox("Runtime Status")
        warning_layout = QVBoxLayout(warning_group)
        self.runtime_warning_label = QLabel("Checking runtime identity...")
        self.runtime_warning_label.setWordWrap(True)
        self.runtime_warning_label.setObjectName("RuntimeWarningLabel")
        warning_layout.addWidget(self.runtime_warning_label)
        root.addWidget(warning_group)

        details_group = QGroupBox("Runtime Diagnostics")
        details_layout = QVBoxLayout(details_group)
        self.runtime_identity_text = QPlainTextEdit()
        self.runtime_identity_text.setReadOnly(True)
        self.runtime_identity_text.setMinimumHeight(260)
        details_layout.addWidget(self.runtime_identity_text)
        root.addWidget(details_group)

        actions = QHBoxLayout()
        self.refresh_runtime_identity_button = QPushButton("Refresh Diagnostics")
        self.copy_runtime_identity_button = QPushButton("Copy Diagnostics")
        self.runtime_copy_status_label = QLabel("Ready.")
        actions.addWidget(self.refresh_runtime_identity_button)
        actions.addWidget(self.copy_runtime_identity_button)
        actions.addWidget(self.runtime_copy_status_label, stretch=1)
        root.addLayout(actions)
        root.addStretch(1)
        return page

    def _build_overlay_settings_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addWidget(QLabel("Training Overlay"))

        group = QGroupBox("Overlay")
        form = QFormLayout(group)
        self.setting_overlay_enabled = QCheckBox("Show the training overlay")
        self.setting_overlay_opacity = QDoubleSpinBox()
        self.setting_overlay_opacity.setRange(0.20, 1.00)
        self.setting_overlay_opacity.setSingleStep(0.05)
        self.setting_overlay_opacity.setDecimals(2)
        self.setting_overlay_scale = QDoubleSpinBox()
        self.setting_overlay_scale.setRange(0.75, 1.50)
        self.setting_overlay_scale.setSingleStep(0.05)
        self.setting_overlay_scale.setDecimals(2)
        self.setting_overlay_position = QComboBox()
        self.setting_overlay_position.addItem("Top left", "top_left")
        self.setting_overlay_position.addItem("Top right", "top_right")
        self.setting_overlay_position.addItem("Bottom left", "bottom_left")
        self.setting_overlay_position.addItem("Bottom right", "bottom_right")
        self.setting_overlay_position.addItem("Center top", "center_top")
        self.setting_overlay_position.addItem("Custom", "custom")
        self.setting_overlay_click_through = QCheckBox(
            "Allow clicks to pass through the overlay"
        )
        self.setting_overlay_always_on_top = QCheckBox("Keep overlay always on top")
        self.setting_overlay_minimal = QCheckBox("Hide compact status text")
        self.overlay_toggle_button = QPushButton("Show / Hide Overlay")

        form.addRow("Enabled:", self.setting_overlay_enabled)
        form.addRow("Opacity:", self.setting_overlay_opacity)
        form.addRow("Scale:", self.setting_overlay_scale)
        form.addRow("Position:", self.setting_overlay_position)
        form.addRow("Click-through:", self.setting_overlay_click_through)
        form.addRow("Always on top:", self.setting_overlay_always_on_top)
        form.addRow("Minimal mode:", self.setting_overlay_minimal)
        form.addRow("", self.overlay_toggle_button)
        root.addWidget(group)

        note = QLabel(
            "The overlay displays only Radiante Daily session and input state. "
            "It does not inspect, attach to, or control the game."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        root.addStretch(1)
        return page

    def _build_protocol_settings_group(self) -> QGroupBox:
        protocol_group = QGroupBox("Protocol and Session")
        protocol_form = QFormLayout(protocol_group)
        protocol_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        protocol_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.setting_episode_timeout = self.make_seconds_spin(0.10, 10.00)
        self.setting_click_cooldown = self.make_seconds_spin(0.00, 5.00)
        self.setting_stationary_clean = QCheckBox("Count a standing click as a clean hit")
        self.setting_stationary_release = self.make_seconds_spin(0.00, 2.00)
        self.setting_require_release = QCheckBox("Require A/D release at click time")
        self.setting_diagonal_rule = QComboBox()
        self.setting_diagonal_rule.addItem("Strict Footwork", "strict_footwork")
        self.setting_diagonal_rule.addItem("Shot-Linked", "shot_linked")
        self.setting_diagonal_rule.addItem("Informational", "informational")
        self.setting_diagonal_rule.addItem("Disabled", "disabled")
        self.setting_auto_arm = QCheckBox("Enable Auto-Arm session start")
        self.setting_ranked_entry_cost = self.make_int_spin(0, 100000)
        self.setting_ranked_bonus = self.make_int_spin(0, 100000)
        protocol_form.addRow("Episode timeout:", self.setting_episode_timeout)
        protocol_form.addRow("Post-click cooldown:", self.setting_click_cooldown)
        protocol_form.addRow("Standing shot rule:", self.setting_stationary_clean)
        protocol_form.addRow("Minimum release window:", self.setting_stationary_release)
        protocol_form.addRow("A/D release rule:", self.setting_require_release)
        protocol_form.addRow("Diagonal Footwork:", self.setting_diagonal_rule)
        protocol_form.addRow("Session start:", self.setting_auto_arm)
        protocol_form.addRow("Ranked entry cost:", self.setting_ranked_entry_cost)
        protocol_form.addRow("Ranked bonus / clean hit:", self.setting_ranked_bonus)
        return protocol_group

    def _build_input_settings_group(self) -> QGroupBox:
        input_group = QGroupBox("Input Timing")
        input_form = QFormLayout(input_group)
        input_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        input_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.setting_input_enabled = QCheckBox("Track key, mouse, and scroll duration")
        self.setting_capture_mode = QComboBox()
        self.setting_capture_mode.addItem("Performance", "performance")
        self.setting_capture_mode_warning = QLabel("Performance capture is always enabled.")
        self.setting_capture_mode_warning.setWordWrap(True)
        self.setting_tap_max = self.make_seconds_spin(0.01, 2.00)
        self.setting_burst_max = self.make_seconds_spin(0.05, 5.00)
        self.setting_crouch_fire_max = self.make_seconds_spin(0.05, 5.00)
        input_form.addRow("Input timing:", self.setting_input_enabled)
        input_form.addRow("Tap max:", self.setting_tap_max)
        input_form.addRow("Burst max:", self.setting_burst_max)
        input_form.addRow("Crouch+fire max:", self.setting_crouch_fire_max)
        input_form.addRow("", self.setting_capture_mode_warning)
        return input_group

    def _build_tracker_settings_group(self) -> QGroupBox:
        tracker_group = QGroupBox("Import Settings")
        tracker_form = QFormLayout(tracker_group)
        tracker_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        tracker_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.setting_riot_name = QLineEdit()
        self.setting_riot_tag = QLineEdit()
        self.setting_region = QLineEdit()
        self.setting_platform = QLineEdit()
        self.setting_api_key = QLineEdit()
        self.setting_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.setting_show_api_key = QCheckBox("Show key")
        self.setting_api_key_status = QLabel("Henrik key: not checked")
        self.setting_import_limit = self.make_int_spin(1, 5000)
        self.setting_max_scan = self.make_int_spin(10, 20000)
        self.setting_request_delay = self.make_seconds_spin(0.00, 60.00)
        self.setting_ranked_detail_enrichment = QCheckBox("Fetch ranked detail to fill FK/FD when possible")
        tracker_form.addRow("Riot name:", self.setting_riot_name)
        tracker_form.addRow("Riot tag:", self.setting_riot_tag)
        tracker_form.addRow("Region:", self.setting_region)
        tracker_form.addRow("Platform:", self.setting_platform)
        tracker_form.addRow("Henrik API key:", self.setting_api_key)
        tracker_form.addRow("Key visibility:", self.setting_show_api_key)
        tracker_form.addRow("Key status:", self.setting_api_key_status)
        tracker_form.addRow("Default import limit:", self.setting_import_limit)
        tracker_form.addRow("Max scanned matches:", self.setting_max_scan)
        tracker_form.addRow("Request delay:", self.setting_request_delay)
        tracker_form.addRow("Ranked detail:", self.setting_ranked_detail_enrichment)
        return tracker_group

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel(f"MVP APP {self.APP_VERSION} - Valorant Training / Coins")
        title.setObjectName("TitleLabel")
        self.status_label = QLabel("Status: Manual")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status_label)
        root.addLayout(header)

        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        self.start_button = QPushButton("Start Session (F10)")
        self.finish_button = QPushButton("Stop Session (F10)")
        self.reset_button = QPushButton("Reset Counters (F9)")
        self.refresh_button = QPushButton("Refresh (F6)")
        self.finish_button.setEnabled(False)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.finish_button)
        button_row.addWidget(self.reset_button)
        button_row.addWidget(self.refresh_button)
        button_row.addStretch(1)
        root.addLayout(button_row)

        shell_layout = QHBoxLayout()
        shell_layout.setSpacing(8)
        shell_layout.addWidget(self._build_main_menu(), stretch=0)
        shell_layout.addWidget(self._build_main_content_stack(), stretch=1)
        root.addLayout(shell_layout, stretch=1)

        info_bar = QFrame()
        info_bar.setObjectName("ImportStatusBar")
        info_bar.setMaximumHeight(54)
        info_bar.setVisible(False)
        self.import_status_bar = info_bar
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(8, 4, 8, 4)
        self.info_tracker_label = QLabel("Imports: idle")
        self.info_tracker_progress_bar = QProgressBar()
        self.info_tracker_progress_bar.setRange(0, 1000)
        self.info_tracker_progress_bar.setValue(0)
        self.info_tracker_progress_bar.setFormat("0.0%")
        info_layout.addWidget(QLabel("Import Status:"))
        info_layout.addWidget(self.info_tracker_label)
        info_layout.addWidget(self.info_tracker_progress_bar, stretch=1)
        root.addWidget(info_bar)

        self.setStyleSheet(
            """
            QLabel#TitleLabel {
                font-size: 20px;
                font-weight: bold;
            }
            QLabel#StatusLabel {
                color: #94A3B8;
                font-weight: bold;
            }
            QLabel#RuntimeWarningLabel {
                color: #F59E0B;
                font-weight: bold;
            }
            QFrame#ImportStatusBar {
                border-top: 1px solid rgba(148, 163, 184, 90);
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
        summary_label = QLabel(
            "Use the session controls above for manual start, Auto-Arm, stop, and reset. "
            "Coins stay enabled in Deathmatch."
        )
        summary_label.setWordWrap(True)
        root.addWidget(summary_label)
        root.addWidget(self._build_live_session_group())
        root.addWidget(self._build_input_summary_group())
        root.addStretch(1)
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
        self.setting_diagonal_rule = QComboBox()
        self.setting_diagonal_rule.addItem("Strict Footwork", "strict_footwork")
        self.setting_diagonal_rule.addItem("Shot-Linked", "shot_linked")
        self.setting_diagonal_rule.addItem("Informational", "informational")
        self.setting_diagonal_rule.addItem("Disabled", "disabled")
        self.setting_auto_arm = QCheckBox("Enable Auto-Arm session start")
        protocol_form.addRow("Tempo máximo do episódio:", self.setting_episode_timeout)
        protocol_form.addRow("Cooldown pós-clique:", self.setting_click_cooldown)
        protocol_form.addRow("Disparo parado:", self.setting_stationary_clean)
        protocol_form.addRow("Tempo mínimo parado:", self.setting_stationary_release)
        protocol_form.addRow("Regra extra:", self.setting_require_release)
        protocol_form.addRow("Diagonal footwork (DM):", self.setting_diagonal_rule)
        protocol_form.addRow("Session start:", self.setting_auto_arm)
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
        self.confirm_sell_button.clicked.connect(self.confirm_sell)
        self.clear_selection_button.clicked.connect(self.clear_weapon_selection)
        self.store_mode_combo.currentIndexChanged.connect(self.clear_weapon_selection)
        self.import_tracker_button.clicked.connect(self.import_tracker_deathmatches)
        self.import_ranked_button.clicked.connect(self.import_tracker_rankeds)
        self.prev_month_button.clicked.connect(self.show_previous_month)
        self.today_month_button.clicked.connect(self.show_current_month)
        self.next_month_button.clicked.connect(self.show_next_month)
        if hasattr(self, "import_training_calendar_button"):
            self.import_training_calendar_button.clicked.connect(self.import_training_calendar_csv)
        if hasattr(self, "export_training_calendar_button"):
            self.export_training_calendar_button.clicked.connect(self.export_current_month_calendar)
        self.save_settings_button.clicked.connect(self.save_quick_settings)
        self.reload_settings_button.clicked.connect(self.reload_quick_settings)
        self.reset_settings_button.clicked.connect(self.reset_quick_settings_to_defaults)
        if hasattr(self, "setting_show_api_key"):
            self.setting_show_api_key.toggled.connect(self.toggle_api_key_visibility)
        self.setting_capture_mode.currentIndexChanged.connect(self.refresh_capture_mode_warning)
        self.setting_overlay_enabled.toggled.connect(self.apply_overlay_settings)
        self.setting_overlay_opacity.valueChanged.connect(self.apply_overlay_settings)
        self.setting_overlay_scale.valueChanged.connect(self.apply_overlay_settings)
        self.setting_overlay_position.currentIndexChanged.connect(self.apply_overlay_settings)
        self.setting_overlay_click_through.toggled.connect(self.apply_overlay_settings)
        self.setting_overlay_always_on_top.toggled.connect(self.apply_overlay_settings)
        self.setting_overlay_minimal.toggled.connect(self.apply_overlay_settings)
        self.overlay_toggle_button.clicked.connect(self.toggle_overlay_preview)
        self.refresh_input_debug_button.clicked.connect(self.refresh_input_debug_view)
        self.copy_input_debug_button.clicked.connect(self.copy_input_debug)
        self.save_input_debug_button.clicked.connect(self.save_input_debug_log)
        self.refresh_runtime_identity_button.clicked.connect(self.refresh_runtime_identity)
        self.copy_runtime_identity_button.clicked.connect(self.copy_runtime_identity)

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

    @staticmethod
    def set_combo_data(widget: QComboBox, value: str) -> None:
        index = widget.findData(value)
        if index >= 0:
            widget.setCurrentIndex(index)

    def toggle_api_key_visibility(self, checked: bool) -> None:
        if not hasattr(self, "setting_api_key"):
            return
        self.setting_api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def refresh_api_key_status(self) -> None:
        if not hasattr(self, "setting_api_key"):
            return
        config_key = self.setting_api_key.text().strip()
        active_settings = get_tracker_settings()
        if config_key:
            self.setting_api_key_status.setText("Henrik key: saved in the app")
        elif active_settings.api_key:
            self.setting_api_key_status.setText("Henrik key: using .env or environment variable")
        else:
            self.setting_api_key_status.setText("Henrik key: missing")

    def refresh_capture_mode_warning(self) -> None:
        self.setting_capture_mode_warning.setText("Performance capture is always enabled.")

    def load_settings_into_form(self, config: AppConfig) -> None:
        if hasattr(self, "setting_kcred_clean"):
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
        protocol_settings = dict(config.protocol or {})
        self.set_combo_data(
            self.setting_diagonal_rule,
            str(protocol_settings.get("diagonal_footwork_rule_deathmatch", "strict_footwork")),
        )
        automation_settings = dict(config.session_automation or {})
        self.setting_auto_arm.setChecked(bool(automation_settings.get("auto_arm_enabled", False)))
        ranked_economy = dict(config.ranked_economy or {})
        self.setting_ranked_entry_cost.setValue(int(ranked_economy.get("entry_cost", 0)))
        self.setting_ranked_bonus.setValue(int(ranked_economy.get("bonus_per_clean_hit", 0)))

        input_settings = dict(config.input_timing or {})
        self.setting_input_enabled.setChecked(bool(input_settings.get("enabled", True)))
        self.set_combo_data(
            self.setting_capture_mode,
            str(input_settings.get("capture_mode", "performance")),
        )
        self.setting_tap_max.setValue(float(input_settings.get("tap_max_seconds", 0.12)))
        self.setting_burst_max.setValue(float(input_settings.get("burst_max_seconds", 0.50)))
        self.setting_crouch_fire_max.setValue(float(input_settings.get("crouch_fire_max_seconds", 0.50)))
        self.refresh_capture_mode_warning()

        if hasattr(self, "setting_daily_goal"):
            calendar_settings = dict(config.training_calendar or {})
            self.setting_daily_goal.setValue(float(calendar_settings.get("daily_goal_hours", 2.0)))
            self.setting_light_day.setValue(float(calendar_settings.get("light_day_hours", 0.5)))
            self.setting_medium_day.setValue(float(calendar_settings.get("medium_day_hours", 1.0)))
            self.setting_strong_day.setValue(float(calendar_settings.get("strong_day_hours", 2.0)))

        if hasattr(self, "setting_riot_name"):
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
        self.setting_overlay_enabled.setChecked(bool(config.overlay_enabled))
        self.setting_overlay_opacity.setValue(float(config.overlay_opacity))
        self.setting_overlay_scale.setValue(float(config.overlay_scale))
        self.set_combo_data(self.setting_overlay_position, str(config.overlay_position))
        self.setting_overlay_click_through.setChecked(bool(config.overlay_click_through))
        self.setting_overlay_always_on_top.setChecked(bool(config.overlay_always_on_top))
        self.setting_overlay_minimal.setChecked(bool(config.overlay_minimal_mode))

    def build_config_from_form(self) -> AppConfig:
        current = self.app_config

        tracker_settings = dict(current.tracker or {})
        if hasattr(self, "setting_riot_name"):
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
        if hasattr(self, "setting_daily_goal"):
            calendar_settings.update({
                "daily_goal_hours": self.setting_daily_goal.value(),
                "light_day_hours": self.setting_light_day.value(),
                "medium_day_hours": self.setting_medium_day.value(),
                "strong_day_hours": self.setting_strong_day.value(),
            })

        automation_settings = dict(current.session_automation or {})
        automation_settings.update({
            "auto_arm_enabled": self.setting_auto_arm.isChecked(),
        })

        protocol_settings = dict(current.protocol or {})
        protocol_settings.update({
            "diagonal_footwork_rule_deathmatch": str(self.setting_diagonal_rule.currentData() or "strict_footwork"),
            "diagonal_footwork_rule_ranked": str(protocol_settings.get("diagonal_footwork_rule_ranked") or "informational"),
        })

        input_settings = dict(current.input_timing or {})
        input_settings.update({
            "enabled": self.setting_input_enabled.isChecked(),
            "capture_mode": "performance",
            "tap_max_seconds": self.setting_tap_max.value(),
            "burst_max_seconds": self.setting_burst_max.value(),
            "crouch_fire_max_seconds": self.setting_crouch_fire_max.value(),
        })

        payload = {
            "episode_timeout": self.setting_episode_timeout.value(),
            "post_click_cooldown": self.setting_click_cooldown.value(),
            "require_release_at_click": self.setting_require_release.isChecked(),
            "stationary_click_counts_clean": self.setting_stationary_clean.isChecked(),
            "stationary_min_release_seconds": self.setting_stationary_release.value(),
            "default_starting_balance": current.default_starting_balance,
            "default_next_weapon": current.default_next_weapon,
            "weapons": current.weapons,
            "tracker": tracker_settings,
            "training_calendar": calendar_settings,
            "session_automation": automation_settings,
            "protocol": protocol_settings,
            "ranked_economy": {
                "entry_cost": self.setting_ranked_entry_cost.value(),
                "bonus_per_clean_hit": self.setting_ranked_bonus.value(),
            },
            "overlay_enabled": self.setting_overlay_enabled.isChecked(),
            "overlay_opacity": self.setting_overlay_opacity.value(),
            "overlay_position": str(
                self.setting_overlay_position.currentData() or "top_right"
            ),
            "overlay_custom_x": self.app_config.overlay_custom_x
            if str(self.setting_overlay_position.currentData() or "") == "custom"
            else None,
            "overlay_custom_y": self.app_config.overlay_custom_y
            if str(self.setting_overlay_position.currentData() or "") == "custom"
            else None,
            "overlay_scale": self.setting_overlay_scale.value(),
            "overlay_click_through": self.setting_overlay_click_through.isChecked(),
            "overlay_always_on_top": self.setting_overlay_always_on_top.isChecked(),
            "overlay_minimal_mode": self.setting_overlay_minimal.isChecked(),
            "input_timing": input_settings,
        }
        if hasattr(self, "setting_kcred_clean"):
            payload.update({
                "kcred_per_clean_hit": self.setting_kcred_clean.value(),
                "kcred_penalty_brake_error": self.setting_penalty_brake.value(),
                "kcred_penalty_diagonal_error": self.setting_penalty_diagonal.value(),
                "kcred_penalty_no_ad_error": self.setting_penalty_no_ad.value(),
                "xp_per_clean_hit": self.setting_xp_clean.value(),
                "xp_per_level": self.setting_xp_level.value(),
            })
        else:
            payload.update({
                "kcred_per_clean_hit": current.kcred_per_clean_hit,
                "kcred_penalty_brake_error": current.kcred_penalty_brake_error,
                "kcred_penalty_diagonal_error": current.kcred_penalty_diagonal_error,
                "kcred_penalty_no_ad_error": current.kcred_penalty_no_ad_error,
                "xp_per_clean_hit": current.xp_per_clean_hit,
                "xp_per_level": current.xp_per_level,
            })
        return AppConfig.from_dict(payload)

    def save_quick_settings(self) -> None:
        if self.controller.is_session_active or self.controller.has_pending_purchase:
            QMessageBox.warning(
                self,
                "Settings locked",
                "Finish the active session and any pending purchase before saving settings.",
            )
            return

        config = self.build_config_from_form()
        save_config(config)
        self.app_config = load_config()
        self.calendar_settings = self.app_config.training_calendar
        self.controller = AppController()
        self.overlay_window.state_provider = self.controller.get_overlay_snapshot
        self.refresh_runtime_identity()
        self.last_runtime_revision = -1
        self.refresh_api_key_status()
        self.apply_overlay_settings()
        self.refresh_all()
        self.settings_status_label.setText("Settings saved and reloaded.")
        QMessageBox.information(
            self,
            "Settings saved",
            "Settings were saved. Protocol and input timing changes apply to future sessions.",
        )

    def reload_quick_settings(self) -> None:
        self.app_config = load_config()
        self.calendar_settings = self.app_config.training_calendar
        self.load_settings_into_form(self.app_config)
        self.refresh_runtime_identity()
        self.last_runtime_revision = -1
        self.refresh_api_key_status()
        self.apply_overlay_settings()
        self.refresh_training_calendar_table()
        self.settings_status_label.setText("Settings reloaded from file.")

    def reset_quick_settings_to_defaults(self) -> None:
        default_config = AppConfig()
        self.load_settings_into_form(default_config)
        self.apply_overlay_settings()
        self.settings_status_label.setText("Defaults loaded on screen. Save settings to apply them.")

    def refresh_runtime_identity(self) -> None:
        identity = collect_runtime_identity(
            app_version=self.APP_VERSION,
            project_root=PROJECT_ROOT,
            launch_entry_file=PROJECT_ROOT / "launch.pyw",
        )
        self.runtime_identity_warnings = list(identity.warnings)
        self.runtime_identity_text.setPlainText(identity.as_text())
        if identity.warnings:
            self.runtime_warning_label.setText("\n".join(f"Warning: {item}" for item in identity.warnings))
        else:
            self.runtime_warning_label.setText("Runtime identity looks consistent.")
        self.runtime_copy_status_label.setText("Diagnostics refreshed.")

    def copy_runtime_identity(self) -> None:
        diagnostics = self.runtime_identity_text.toPlainText().strip()
        warnings = "\n".join(f"Warning: {item}" for item in getattr(self, "runtime_identity_warnings", []))
        text = diagnostics if not warnings else f"{diagnostics}\n\n{warnings}"
        QApplication.clipboard().setText(text)
        self.runtime_copy_status_label.setText("Diagnostics copied to clipboard.")

    def get_overlay_debug_timing(self) -> tuple[int, int | None]:
        interval_ms = int(getattr(self.overlay_window, "UPDATE_INTERVAL_MS", 0) or 0)
        age_ms = (
            self.overlay_window.last_refresh_age_ms()
            if hasattr(self.overlay_window, "last_refresh_age_ms")
            else None
        )
        return interval_ms, age_ms

    def get_input_debug_snapshot(self) -> dict[str, object]:
        overlay_interval_ms, overlay_age_ms = self.get_overlay_debug_timing()
        snapshot = self.controller.get_input_debug_snapshot(
            overlay_update_interval_ms=overlay_interval_ms,
            overlay_last_refresh_age_ms=overlay_age_ms,
        )
        snapshot["overlay_input_pulse_ms"] = int(
            getattr(self.overlay_window, "INPUT_PULSE_MS", 0) or 0
        )
        snapshot["overlay_scroll_pulse_ms"] = int(
            getattr(self.overlay_window, "SCROLL_PULSE_MS", 0) or 0
        )
        return snapshot

    def refresh_input_debug_view(self) -> None:
        snapshot = self.get_input_debug_snapshot()
        active_keys = [
            key
            for key, active in dict(snapshot.get("active_keys") or {}).items()
            if active
        ]
        active_text = ", ".join(active_keys) if active_keys else "-"
        overlay_age = snapshot.get("overlay_last_refresh_age_ms")
        overlay_age_text = "-" if overlay_age is None else f"{overlay_age} ms"
        self.input_debug_body_state_label.setText(f"Body state: {snapshot.get('body_state', '-')}")
        self.input_debug_active_keys_label.setText(f"Active keys: {active_text}")
        self.input_debug_last_fire_label.setText(f"Last fire state: {snapshot.get('last_fire_state', '-')}")
        self.input_debug_windows_label.setText(
            "Jump: "
            f"{'active' if snapshot.get('jump_window_active') else 'inactive'} "
            f"({snapshot.get('jump_window_remaining_ms', 0)} ms) | "
            "Brake: "
            f"{'active' if snapshot.get('brake_window_active') else 'inactive'} "
            f"({snapshot.get('brake_window_remaining_ms', 0)} ms)"
        )
        self.input_debug_overlay_label.setText(
            f"Overlay: interval {snapshot.get('overlay_update_interval_ms') or '-'} ms | "
            f"pulse {snapshot.get('overlay_input_pulse_ms') or '-'} ms | "
            f"last refresh age {overlay_age_text}"
        )
        self.input_debug_ratios_label.setText(
            "Ratios: "
            f"Diag {snapshot.get('diagonal_ratio_percent', 0.0)}% "
            f"({snapshot.get('diagonal_time_ms', 0)} / {snapshot.get('movement_time_ms', 0)} ms) | "
            f"Brake {snapshot.get('missed_brake_ratio_percent', 0.0)}% "
            f"({snapshot.get('missed_brake_count', 0)} / {snapshot.get('brake_opportunity_count', 0)}) | "
            f"Pressure Diag {snapshot.get('diagonal_pressure_percent', 0.0)}% | "
            f"Brake {snapshot.get('brake_pressure_percent', 0.0)}%"
        )
        self.input_debug_warnings_label.setText(
            f"Warnings: {self.format_warning_summary(snapshot)}"
        )
        self.input_debug_text.setPlainText(self.format_input_debug_snapshot(snapshot))
        self.input_debug_copy_status_label.setText("Input debug refreshed.")

    def copy_input_debug(self) -> None:
        snapshot = self.get_input_debug_snapshot()
        QApplication.clipboard().setText(json.dumps(snapshot, indent=2, sort_keys=True))
        self.input_debug_copy_status_label.setText("Input debug copied to clipboard.")

    def save_input_debug_log(self) -> None:
        export_dir = DATA_DIR / "debug_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("input_debug_%Y%m%d_%H%M%S")
        path = export_dir / f"{stamp}.txt"
        suffix = 1
        while path.exists():
            path = export_dir / f"{stamp}_{suffix}.txt"
            suffix += 1
        text = self.build_input_debug_log_text()
        path.write_text(text, encoding="utf-8")
        QApplication.clipboard().setText(str(path))
        self.input_debug_copy_status_label.setText(f"Saved: {path}")

    def build_input_debug_log_text(self) -> str:
        identity = collect_runtime_identity(
            app_version=self.APP_VERSION,
            project_root=PROJECT_ROOT,
            launch_entry_file=PROJECT_ROOT / "launch.pyw",
        )
        snapshot = self.get_input_debug_snapshot()
        warnings = snapshot.get("current_warnings") or snapshot.get("warning_counts") or {}
        lines = [
            "Radiante Daily Input Debug Log",
            "",
            "Runtime",
            identity.as_text(),
            "",
            "Input Debug",
            self.format_input_debug_snapshot(snapshot),
            "",
            "Warnings / Infractions",
            json.dumps(warnings, indent=2, sort_keys=True),
            "",
            "Raw Snapshot",
            json.dumps(snapshot, indent=2, sort_keys=True),
        ]
        return "\n".join(lines)

    @staticmethod
    def format_input_debug_snapshot(snapshot: dict[str, object]) -> str:
        lines = [
            f"Capture enabled: {snapshot.get('enabled')}",
            f"Body state: {snapshot.get('body_state')}",
            f"Last fire state: {snapshot.get('last_fire_state')}",
            f"Jump window active: {snapshot.get('jump_window_active')} ({snapshot.get('jump_window_remaining_ms')} ms)",
            f"Brake window active: {snapshot.get('brake_window_active')} ({snapshot.get('brake_window_remaining_ms')} ms)",
            f"Overlay interval: {snapshot.get('overlay_update_interval_ms')} ms",
            f"Overlay input pulse: {snapshot.get('overlay_input_pulse_ms')} ms",
            f"Overlay scroll pulse: {snapshot.get('overlay_scroll_pulse_ms')} ms",
            f"Overlay last refresh age: {snapshot.get('overlay_last_refresh_age_ms')}",
            f"Diagonal ratio: {snapshot.get('diagonal_ratio_percent')}% ({snapshot.get('diagonal_time_ms')} / {snapshot.get('movement_time_ms')} ms)",
            "Missed brake ratio: "
            f"{snapshot.get('missed_brake_ratio_percent')}% "
            f"({snapshot.get('missed_brake_count')} / {snapshot.get('brake_opportunity_count')})",
            f"Diagonal pressure: {snapshot.get('diagonal_pressure_percent')}%",
            f"Brake pressure: {snapshot.get('brake_pressure_percent')}%",
            f"Last expected brake key: {snapshot.get('last_expected_brake_key') or '-'}",
            f"Last missed brake direction: {snapshot.get('last_missed_brake_direction') or '-'}",
            f"Last release to fire: {snapshot.get('last_release_to_fire_ms')}",
            f"Current warnings: {MainWindow.format_warning_summary(snapshot)}",
            "",
            "Active keys:",
            json.dumps(snapshot.get("active_keys") or {}, sort_keys=True),
            "",
            "Event counters by input:",
            json.dumps(snapshot.get("event_counts_by_input") or {}, sort_keys=True),
            "",
            "Event counters by action:",
            json.dumps(snapshot.get("event_counts_by_action") or {}, sort_keys=True),
            "",
            "Warning counters:",
            json.dumps(snapshot.get("warning_counts") or {}, sort_keys=True),
            "",
            "Recent raw events:",
        ]
        events = list(snapshot.get("recent_events") or [])
        if not events:
            lines.append("No raw input events captured yet.")
            return "\n".join(lines)

        for event in events[-40:]:
            if not isinstance(event, dict):
                continue
            lines.append(
                "#"
                f"{event.get('event_index')} "
                f"{event.get('event_type')} "
                f"{event.get('input_id')} -> {event.get('action')} "
                f"body={event.get('body_state')} "
                f"t={event.get('monotonic_timestamp')}"
            )
        return "\n".join(lines)

    @staticmethod
    def warning_label(name: object) -> str:
        labels = {
            "diagonal_movement": "Diagonal movement",
            "fire_while_moving": "Firing while moving",
            "fire_while_jumping": "Firing while jumping",
            "fire_during_unstable_brake": "Firing during unstable brake",
            "long_strafe_hold": "Long strafe hold / slow release",
        }
        return labels.get(str(name), str(name).replace("_", " ").title())

    @staticmethod
    def format_warning_summary(snapshot: dict[str, object]) -> str:
        current = [
            MainWindow.warning_label(name)
            for name in list(snapshot.get("current_warnings") or [])
        ]
        counts = dict(snapshot.get("warning_counts") or {})
        count_text = ", ".join(
            f"{MainWindow.warning_label(name)}={count}"
            for name, count in sorted(counts.items())
        )
        active_text = ", ".join(current) if current else "none active"
        return f"{active_text} | counts: {count_text or 'none'}"

    def overlay_settings_from_form(self) -> dict[str, object]:
        return {
            "overlay_enabled": self.setting_overlay_enabled.isChecked(),
            "overlay_opacity": self.setting_overlay_opacity.value(),
            "overlay_position": str(
                self.setting_overlay_position.currentData() or "top_right"
            ),
            "overlay_custom_x": self.app_config.overlay_custom_x
            if str(self.setting_overlay_position.currentData() or "") == "custom"
            else None,
            "overlay_custom_y": self.app_config.overlay_custom_y
            if str(self.setting_overlay_position.currentData() or "") == "custom"
            else None,
            "overlay_scale": self.setting_overlay_scale.value(),
            "overlay_click_through": self.setting_overlay_click_through.isChecked(),
            "overlay_always_on_top": self.setting_overlay_always_on_top.isChecked(),
            "overlay_minimal_mode": self.setting_overlay_minimal.isChecked(),
        }

    def apply_overlay_settings(self, *_args) -> None:
        if not hasattr(self, "overlay_window"):
            return
        self.overlay_window.apply_settings(self.overlay_settings_from_form())

    def save_overlay_position(self, x: int, y: int) -> None:
        payload = self.app_config.to_dict()
        payload.update({
            "overlay_position": "custom",
            "overlay_custom_x": int(x),
            "overlay_custom_y": int(y),
        })
        self.app_config = AppConfig.from_dict(payload)
        save_config(self.app_config)
        self.setting_overlay_position.blockSignals(True)
        self.set_combo_data(self.setting_overlay_position, "custom")
        self.setting_overlay_position.blockSignals(False)
        self.overlay_window.settings.update({
            "overlay_position": "custom",
            "overlay_custom_x": int(x),
            "overlay_custom_y": int(y),
        })
        self.settings_status_label.setText("Overlay position saved.")

    def toggle_overlay_preview(self) -> None:
        if self.overlay_window.isVisible():
            self.overlay_window.hide()
            return
        self.overlay_window.apply_settings(
            {
                **self.overlay_settings_from_form(),
                "overlay_enabled": True,
            }
        )

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
        self._ensure_keyboard_listener()
        self._update_capture_listeners()

    def _ensure_keyboard_listener(self) -> None:
        if self.keyboard_listener is not None and self.keyboard_listener.running:
            return

        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self.keyboard_listener.start()

    def _ensure_mouse_listener(self) -> None:
        if self.mouse_listener is not None and self.mouse_listener.running:
            return

        self.mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self.mouse_listener.start()

    def _stop_mouse_listener(self) -> None:
        if self.mouse_listener is not None and self.mouse_listener.running:
            self.mouse_listener.stop()
        self.mouse_listener = None

    def _update_capture_listeners(self) -> None:
        capture_enabled = self.controller.capture_mode != "off"
        if capture_enabled and (self.controller.is_session_active or self.is_auto_arm_enabled()):
            self._ensure_mouse_listener()
        else:
            self._stop_mouse_listener()

    def is_auto_arm_enabled(self) -> bool:
        settings = dict(self.app_config.session_automation or {})
        return bool(settings.get("auto_arm_enabled", False))

    def get_runtime_status_text(self) -> str:
        if self.controller.is_session_active:
            if self.controller.current_session_mode == "ranked":
                return "Ranked Audit Active"
            return "Session Active"
        if self.is_auto_arm_enabled():
            return "Auto-Armed"
        return "Manual"

    def get_foreground_window_title(self) -> str:
        if os.name != "nt":
            return ""

        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return ""
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return ""
            buffer = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
            return buffer.value.strip()
        except Exception:
            return ""

    def is_valorant_focused(self) -> bool:
        return "valorant" in self.get_foreground_window_title().lower()

    def update_live_refresh_interval(self) -> None:
        target_interval = (
            self.ACTIVE_SESSION_UPDATE_INTERVAL_MS
            if self.controller.is_session_active
            else self.LIVE_UPDATE_INTERVAL_MS
        )
        if self.live_timer.interval() != target_interval:
            self.live_timer.start(target_interval)

    def is_debug_view_active(self) -> bool:
        return (
            getattr(self, "main_stack", None) is not None
            and getattr(self, "settings_stack", None) is not None
            and self.main_stack.currentWidget() is self.main_pages.get("settings")
            and self.settings_stack.currentIndex() == 4
        )

    def is_input_debug_view_active(self) -> bool:
        return (
            getattr(self, "main_stack", None) is not None
            and getattr(self, "settings_stack", None) is not None
            and self.main_stack.currentWidget() is self.main_pages.get("settings")
            and self.settings_stack.currentIndex() == 1
        )

    def maybe_auto_start_session(self, trigger_input: str) -> bool:
        if self.controller.is_session_active:
            return False
        if self.controller.capture_mode == "off":
            return False
        if not self.is_auto_arm_enabled():
            return False
        if self.controller.has_pending_purchase:
            return False
        if trigger_input not in {"w", "a", "s", "d", "mouse_left"}:
            return False
        if self.selected_session_mode() not in {"deathmatch", "ranked"}:
            return False
        if not self.is_valorant_focused():
            return False

        try:
            start_data = self.controller.start_session(
                self.selected_session_mode(),
                start_source="auto_arm",
            )
        except RuntimeError:
            return False

        self._update_capture_listeners()
        self.current_weapon_label.setText(f"Session weapon: {start_data['weapon']}")
        self.refresh_live_stats()
        self.refresh_buttons()
        return True

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
        key_name = self.get_key_name(key)
        if not self.controller.is_session_active:
            self.maybe_auto_start_session(key_name)
        if not self.controller.is_session_active:
            return
        self.controller.handle_key_press(key_name)

    def _on_key_release(self, key):
        if not self.controller.is_session_active:
            return
        self.controller.handle_key_release(self.get_key_name(key))

    def _on_click(self, x, y, button, pressed):
        button_name = InputTimingTracker.mouse_button_to_input_id(button)
        if not self.controller.is_session_active and pressed:
            self.maybe_auto_start_session(button_name)
        if not self.controller.is_session_active:
            return
        self.controller.handle_mouse_button(button_name, bool(pressed))

    def _on_scroll(self, x, y, dx, dy):
        if not self.controller.is_session_active:
            return
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

    @staticmethod
    def translate_runtime_error(error: Exception) -> str:
        text = str(error).strip()
        translations = {
            "Existe uma compra pendente antes da próxima sessão.": "There is a pending purchase before the next session.",
            "A sessão já está ativa.": "A session is already active.",
            "Não existe sessão ativa para encerrar.": "There is no active session to finish.",
            "Não é possível trocar o modo com sessão ativa.": "You cannot change modes while a session is active.",
            "Conclua a compra pendente antes de trocar o modo.": "Finish the pending purchase before changing modes.",
            "Não existe sessão finalizada aguardando compra.": "There is no finished session waiting for purchase confirmation.",
        }
        if text.startswith("Arma inválida:"):
            weapon_name = text.split(":", 1)[1].strip()
            return f"Invalid weapon: {weapon_name}"
        return translations.get(text, text)

    def start_session(self) -> None:
        if self.controller.has_pending_purchase:
            QMessageBox.information(self, "Pending purchase", "Confirm the next weapon before starting another Deathmatch session.")
            return
        start_data = self.controller.start_session(self.selected_session_mode(), start_source="manual")
        self._update_capture_listeners()
        self.current_weapon_label.setText(f"Session weapon: {start_data['weapon']}")
        self.refresh_live_stats()
        self.refresh_buttons()

    def finish_session(self) -> None:
        if not self.controller.is_session_active:
            return
        result = self.controller.finish_session()
        self._update_capture_listeners()
        if result.session_mode == "deathmatch":
            self.set_combo_data(self.store_mode_combo, "equip")
            self.populate_weapon_combo()
            self.show_main_page("inventory")
            self._set_subpage(self.inventory_stack, 1, self.inventory_buttons)
        self.refresh_all()

    def reset_counters(self) -> None:
        self.controller.reset_counters()
        self._update_capture_listeners()
        self.refresh_live_stats()

    def confirm_purchase(self) -> None:
        if self.controller.last_finished_session is None:
            try:
                self.controller.buy_inventory_cart(self.weapon_selection_counts)
            except ValueError as error:
                QMessageBox.warning(self, "Purchase failed", str(error))
            else:
                self.clear_weapon_selection()
                self.refresh_all()
            return
        weapon_name = self.selected_weapon_name()
        try:
            self.controller.confirm_purchase_by_name(weapon_name)
        except (RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "Purchase failed", self.translate_runtime_error(error))
            return
        self.refresh_all()

    def confirm_sell(self) -> None:
        try:
            self.controller.sell_inventory_cart(self.weapon_selection_counts)
        except ValueError as error:
            QMessageBox.warning(self, "Sale failed", str(error))
            return
        self.clear_weapon_selection()
        self.refresh_all()

    def selected_weapon_name(self) -> str:
        selected = [name for name, quantity in self.weapon_selection_counts.items() if quantity > 0]
        return selected[-1] if selected else "Classic"

    def clear_weapon_selection(self) -> None:
        self.weapon_selection_counts.clear()
        self.populate_weapon_combo()

    def select_weapon(self, weapon_name: str) -> None:
        items = {item["name"]: item for item in self.controller.get_available_weapons()}
        item = items.get(weapon_name)
        if item is None:
            return
        mode = str(self.store_mode_combo.currentData() or "buy")
        if mode == "equip":
            if not item.get("owned"):
                return
            try:
                if self.controller.has_pending_purchase:
                    self.controller.confirm_purchase_by_name(weapon_name)
                else:
                    self.controller.equip_weapon(weapon_name)
            except (RuntimeError, ValueError) as error:
                QMessageBox.warning(self, "Equip failed", self.translate_runtime_error(error))
            self.refresh_all()
            return
        if weapon_name == "Classic":
            return
        limit = int(item.get("owned_quantity", 0)) if mode == "sell" else 999
        current = int(self.weapon_selection_counts.get(weapon_name, 0))
        if current < limit:
            self.weapon_selection_counts[weapon_name] = current + 1
        self.populate_weapon_combo()

    def decrement_weapon_selection(self, weapon_name: str) -> None:
        current = int(self.weapon_selection_counts.get(weapon_name, 0))
        if current <= 0:
            return
        if current == 1:
            self.weapon_selection_counts.pop(weapon_name, None)
        else:
            self.weapon_selection_counts[weapon_name] = current - 1
        self.populate_weapon_combo()

    def refresh_import_mode(self, ranked: bool) -> None:
        mode = self.ranked_import_mode if ranked else self.dm_import_mode
        season = self.ranked_season_selector if ranked else self.dm_season_selector
        from_date = self.ranked_from_date if ranked else self.import_from_date
        to_date = self.ranked_to_date if ranked else self.import_to_date
        value = str(mode.currentData() or "update")
        season.setEnabled(value == "season")
        from_date.setEnabled(value == "range")
        to_date.setEnabled(value == "range")

    def validate_import_dates(self, from_date: QDateEdit, to_date: QDateEdit) -> bool:
        today = QDate.currentDate()
        if from_date.date() > today or to_date.date() > today:
            QMessageBox.warning(self, "Invalid range", "Import dates cannot be in the future.")
            return False
        if from_date.date() > to_date.date():
            QMessageBox.warning(self, "Invalid range", "The From date cannot be later than the To date.")
            return False
        return True

    def selected_session_mode(self) -> str:
        return "ranked" if self.game_modes_stack.currentIndex() == 1 else "deathmatch"

    def select_game_mode(self, session_mode: str) -> None:
        try:
            self.controller.set_session_mode(session_mode)
        except RuntimeError as error:
            QMessageBox.warning(self, "Mode locked", self.translate_runtime_error(error))
            self.set_game_mode_page(self.controller.current_session_mode)
            return

        self._update_capture_listeners()
        self.refresh_live_stats()
        self.refresh_buttons()

    def set_game_mode_page(self, session_mode: str) -> None:
        index = 1 if session_mode == "ranked" else 0
        if self.game_modes_stack.currentIndex() != index:
            self._set_subpage(self.game_modes_stack, index, self.game_modes_buttons)

    def import_tracker_deathmatches(self) -> None:
        mode = str(self.dm_import_mode.currentData() or "update")
        if mode == "range":
            if not self.validate_import_dates(self.import_from_date, self.import_to_date):
                return
            self.run_tracker_import(
                import_all=True,
                start_date=self.import_from_date.date().toString("yyyy-MM-dd"),
                end_date=self.import_to_date.date().toString("yyyy-MM-dd"),
                replace_date_range=True,
            )
            return
        self.run_tracker_import(import_all=mode == "season")

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
            QMessageBox.warning(self, "Invalid range", "The end date cannot be earlier than the start date.")
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
        self.set_tracker_progress(0.0, "Tracker: importing")

        def on_progress(progress: dict) -> None:
            percent = float(progress.get("percent", 0.0))
            self.set_tracker_progress(percent, "Tracker: importing")
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
            QMessageBox.warning(self, "Import failed", str(error))
            self.set_tracker_progress(0.0, "Tracker: failed")
        else:
            self.set_tracker_progress(result.percent, "Tracker: complete")
            if result.message:
                QMessageBox.information(self, "Import", result.message)
            self.refresh_all()
        finally:
            self.set_tracker_import_controls_enabled(True)
            self.refresh_import_mode(False)

    def import_tracker_rankeds(self) -> None:
        mode = str(self.ranked_import_mode.currentData() or "update")
        if mode == "range":
            if not self.validate_import_dates(self.ranked_from_date, self.ranked_to_date):
                return
            self.run_ranked_import(
                import_all=True,
                start_date=self.ranked_from_date.date().toString("yyyy-MM-dd"),
                end_date=self.ranked_to_date.date().toString("yyyy-MM-dd"),
                replace_date_range=True,
            )
            return
        self.run_ranked_import(import_all=mode == "season")

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
            QMessageBox.warning(self, "Invalid range", "The end date cannot be earlier than the start date.")
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
        self.set_tracker_progress(0.0, "Ranked: importing")

        def on_progress(progress: dict) -> None:
            percent = float(progress.get("percent", 0.0))
            self.set_tracker_progress(percent, "Ranked: importing")
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
            QMessageBox.warning(self, "Ranked import failed", str(error))
            self.set_tracker_progress(0.0, "Ranked: failed")
        else:
            self.set_tracker_progress(result.percent, "Ranked: complete")
            if result.message:
                QMessageBox.information(self, "Ranked Import", result.message)
            self.refresh_all()
        finally:
            self.set_ranked_import_controls_enabled(True)
            self.refresh_import_mode(True)

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
        available_weapons = self.controller.get_available_weapons()
        for layout_index in range(4):
            layout = getattr(self.inventory_screen, f"weapon_group_layout_{layout_index}")
            while layout.count():
                layout_item = layout.takeAt(0)
                if layout_item.widget() is not None:
                    layout_item.widget().deleteLater()
        self.weapon_button_widgets.clear()
        for item in available_weapons:
            badges = []
            if item.get("owned"):
                badges.append("ARS")
            if item.get("selected_next"):
                badges.append("NEXT")
            suffix = f" [{'/'.join(badges)}]" if badges else ""
            label = f"{item['name']} | {item['cost']} Coins{suffix}"
            self.weapon_combo.addItem(label, item["name"])
            if not item.get("available"):
                index = self.weapon_combo.count() - 1
                model_item = self.weapon_combo.model().item(index)
                if model_item is not None:
                    model_item.setEnabled(False)
            button = WeaponButton(item["name"])
            button.setToolTip(
                f"{item['name']} | {item['cost']} Coins | owned {item.get('owned_quantity', 0)} | right-click removes one selected"
            )
            selected = int(self.weapon_selection_counts.get(item["name"], 0))
            if selected:
                button.setText(f"{item['name']} ({selected})")
            button.clicked.connect(lambda _=False, name=item["name"]: self.select_weapon(name))
            button.right_clicked.connect(lambda name=item["name"]: self.decrement_weapon_selection(name))
            group_names = ["Sidearms", "SMGs / Shotguns", "Rifles", "Snipers / Heavies"]
            group_index = group_names.index(item.get("group")) if item.get("group") in group_names else 0
            getattr(self.inventory_screen, f"weapon_group_layout_{group_index}").addWidget(button)
            self.weapon_button_widgets[item["name"]] = button
        mode = str(self.store_mode_combo.currentData() or "buy")
        selected_lines = [
            f"{name} x{quantity}"
            for name, quantity in self.weapon_selection_counts.items()
            if quantity > 0
        ]
        total = sum(
            int(item["cost"]) * int(self.weapon_selection_counts.get(item["name"], 0))
            for item in available_weapons
        )
        self.cart_summary_label.setText(
            "Selected weapons: " + (", ".join(selected_lines) or "none")
        )
        self.cart_total_label.setText(
            f"{'Refund' if mode == 'sell' else 'Total cost'}: {total} Coins"
        )
        self.confirm_purchase_button.setVisible(mode == "buy" or self.controller.has_pending_purchase)
        self.confirm_sell_button.setVisible(mode == "sell" and not self.controller.has_pending_purchase)
        self.refresh_inventory_details(available_weapons)

    def refresh_runtime_state(self) -> None:
        self.update_live_refresh_interval()
        current_revision = self.controller.runtime_revision
        if (not self.controller.is_session_active) and current_revision == self.last_runtime_revision:
            return

        self.refresh_live_stats()
        self.refresh_buttons()
        self.last_runtime_revision = current_revision

    def refresh_buttons(self) -> None:
        is_active = self.controller.is_session_active
        has_pending_purchase = self.controller.has_pending_purchase
        self.update_live_refresh_interval()
        self._update_capture_listeners()
        self.status_label.setText(f"Status: {self.get_runtime_status_text()}")
        self.start_button.setEnabled((not is_active) and (not has_pending_purchase))
        self.finish_button.setEnabled(is_active)
        self.reset_button.setEnabled(is_active)
        mode_enabled = (not is_active) and (not has_pending_purchase)
        for button in self.game_modes_buttons:
            button.setEnabled(mode_enabled)
        self.weapon_combo.setEnabled(has_pending_purchase)
        self.confirm_purchase_button.setEnabled(has_pending_purchase or bool(self.weapon_selection_counts))
        self.set_game_mode_page(self.controller.current_session_mode)
        if is_active:
            if self.controller.current_session_mode == "ranked":
                self.purchase_status_label.setText("Ranked audit session is active. Economy settles when the session ends.")
            else:
                self.purchase_status_label.setText("Deathmatch session is active.")
        elif has_pending_purchase:
            self.purchase_status_label.setText("Choose the next weapon for Deathmatch.")
        else:
            if self.controller.current_session_mode == "ranked":
                self.purchase_status_label.setText("Ready to start Ranked audit and economy tracking.")
            else:
                self.purchase_status_label.setText("Ready to start the next Deathmatch session.")
        self.refresh_inventory_details()

    def refresh_all(self) -> None:
        self.populate_weapon_combo()
        self.refresh_dashboard()
        self.refresh_live_stats()
        self.refresh_buttons()
        self.refresh_tracker_table()
        self.refresh_ranked_tab()
        self.refresh_training_calendar_table()
        self.refresh_training_sessions_table()
        self.last_runtime_revision = self.controller.runtime_revision

    def refresh_dashboard(self) -> None:
        stats = self.controller.get_dashboard()
        self.render_dashboard(stats)

    def render_dashboard(self, stats: DashboardStats) -> None:
        self.level_label.setText(f"Level: {stats.progress.level}")
        self.xp_label.setText(
            f"XP: {stats.progress.current_level_xp}/{stats.progress.next_level_xp} | total {stats.progress.total_xp}"
        )
        self.xp_bar.setValue(int(stats.progress.progress_rate * 10))
        self.xp_bar.setFormat(f"{stats.progress.progress_rate:.1f}%")
        self.balance_label.setText(f"Coins: {stats.balance}")
        self.next_weapon_label.setText(f"Next weapon: {stats.next_weapon}")
        self.total_sessions_label.setText(f"Total sessions: {stats.total_sessions}")
        self.avg_rate_label.setText(f"Average protocol rate: {stats.average_protocol_rate:.1f}%")
        self.best_weapon_label.setText(
            f"Best weapon: {stats.best_weapon} ({stats.best_weapon_rate:.1f}%)"
            if stats.best_weapon
            else "Best weapon: -"
        )
        self.today_label.setText(
            f"Today: {stats.today.sessions} sessions | {stats.today.average_protocol_rate:.1f}% | "
            f"+{stats.today.kcreds_earned} Coins"
        )
        self.coins_next_step_label.setText(f"Next step: {stats.next_weapon or '-'}")

        self.tracker_total_label.setText(f"Imported DMs: {stats.tracker.total_matches}")
        self.tracker_kd_label.setText(f"Average KD: {stats.tracker.average_kd:.2f}")
        self.tracker_best_map_label.setText(
            f"Best map: {stats.tracker.best_map} ({stats.tracker.best_map_kd:.2f} KD)"
            if stats.tracker.best_map
            else "Best map: -"
        )
        self.tracker_best_agent_label.setText(
            f"Best agent: {stats.tracker.best_agent} ({stats.tracker.best_agent_kd:.2f} KD)"
            if stats.tracker.best_agent
            else "Best agent: -"
        )

        if stats.tracker.best_match is not None:
            best = stats.tracker.best_match
            self.tracker_best_match_label.setText(
                f"Best DM: {best.map_name} | {best.kills}/{best.deaths}/{best.assists} | {best.kd:.2f} KD"
            )
        else:
            self.tracker_best_match_label.setText("Best DM: -")

        if stats.tracker.last_match is not None:
            last = stats.tracker.last_match
            self.tracker_last_match_label.setText(
                f"Latest DM: {last.date[:10]} | {last.map_name} | {last.agent} | "
                f"{last.kills}/{last.deaths}/{last.assists}"
            )
        else:
            self.tracker_last_match_label.setText("Latest DM: -")

        self.refresh_inventory_details()

    def refresh_inventory_details(self, available_weapons: list[dict] | None = None) -> None:
        wallet = self.controller.get_wallet()
        weapons = available_weapons if available_weapons is not None else self.controller.get_available_weapons()
        current_weapon = str(self.controller.current_weapon or wallet.get("next_weapon") or "-")
        next_weapon = str(wallet.get("next_weapon") or "-")
        available_names = [str(item.get("name") or "-") for item in weapons if item.get("available")]
        owned_count = sum(1 for item in weapons if item.get("owned"))

        self.coins_equipped_label.setText(f"Equipped weapon: {current_weapon}")
        self.weapons_equipped_label.setText(f"Equipped weapon: {current_weapon}")
        self.coins_next_step_label.setText(f"Next step: {next_weapon}")

        if available_names:
            preview = ", ".join(available_names[:5])
            if len(available_names) > 5:
                preview = f"{preview}, ..."
            self.available_weapons_label.setText(
                f"Available weapons now: {len(available_names)} | Owned: {owned_count} | {preview}"
            )
        else:
            self.available_weapons_label.setText(
                f"Available weapons now: none | Owned: {owned_count}"
            )

        if self.controller.has_pending_purchase:
            self.inventory_hint_label.setText(
                "A Deathmatch session is waiting for purchase confirmation in Weapons."
            )
        elif self.controller.current_session_mode == "ranked" and self.controller.is_session_active:
            self.inventory_hint_label.setText(
                "Ranked Audit is active. Entry, refund, and bonus settle when the session ends."
            )
        elif wallet:
            self.inventory_hint_label.setText(
                "Wallet, next weapon, and progression use the current saved local data."
            )
        else:
            self.inventory_hint_label.setText("Wallet data is not available yet.")

    def refresh_tracker_table(self) -> None:
        matches = load_tracker_dm_matches()[:150]
        headers = ["Date", "Map", "Agent", "K", "D", "A", "KD", "Duration", "Weapon", "Protocol"]
        self.tracker_page.setVisible(bool(matches))

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
        if matches:
            self.tracker_status_label.setText(f"Showing {len(matches)} recent imported Deathmatches.")
        else:
            self.tracker_status_label.setText("No imported Deathmatches yet.")

    def refresh_ranked_tab(self) -> None:
        stats = build_ranked_radiante_stats()
        self.ranked_total_label.setText(f"Ranked matches: {stats.total_matches}")
        self.ranked_winrate_label.setText(f"Win rate: {stats.winrate:.1f}% ({stats.wins}W/{stats.losses}L)")
        self.ranked_rr_label.setText(f"Total RR: {stats.total_rr_change:+d} | average {stats.average_rr_change:+.1f}")
        self.ranked_acs_label.setText(f"Average ACS: {stats.average_acs:.1f}")
        self.ranked_adr_label.setText(f"Average ADR: {stats.average_adr:.1f}")
        self.ranked_kast_label.setText(
            f"Average KAST: {stats.average_kast:.1f}%"
            if stats.average_kast
            else "Average KAST: -"
        )
        self.ranked_dd_label.setText(f"Total DDΔ: {stats.total_damage_delta:+d} | DD/R {stats.average_dd_per_round:+.1f}")
        self.ranked_fbfd_label.setText(f"FB {stats.total_first_kills} / FD {stats.total_first_deaths} | Δ {stats.fb_fd_delta:+d}")
        self.ranked_best_map_label.setText(
            f"Best map: {stats.best_map} ({stats.best_map_winrate:.1f}%)"
            if stats.best_map
            else "Best map: -"
        )
        self.ranked_worst_map_label.setText(
            f"Worst map: {stats.worst_map} ({stats.worst_map_winrate:.1f}%)"
            if stats.worst_map
            else "Worst map: -"
        )
        self.ranked_signal_label.setText(f"Dominant signal: {stats.dominant_signal or '-'}")
        self.ranked_focus_label.setText(f"Recommended focus: {stats.next_focus or '-'}")

        matches = load_tracker_ranked_matches()[:150]
        headers = ["Date", "Map", "Agent", "Result", "Rank", "RRΔ", "ACS", "ADR", "DDΔ", "DD/R", "FB", "FD", "FB-FD", "K/D/A"]
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
        if matches:
            self.ranked_history_status_label.setText(f"Showing {len(matches)} recent ranked matches.")
        else:
            self.ranked_history_status_label.setText("No imported ranked matches yet.")

    def refresh_training_calendar_table(self) -> None:
        days = build_training_calendar()
        day_by_date = {day.date: day for day in days}
        self.render_training_calendar_grid(day_by_date)

    def refresh_training_sessions_table(self) -> None:
        sessions = sorted(load_all_sessions(), key=lambda item: (item.finished_at, item.started_at), reverse=True)
        if sessions:
            self.training_sessions_summary_label.setText(f"Training sessions: {len(sessions)} total")
            self.training_sessions_status_label.setText(
                f"Showing the latest {min(len(sessions), 150)} saved sessions."
            )
        else:
            self.training_sessions_summary_label.setText("Training sessions: 0")
            self.training_sessions_status_label.setText("No saved sessions yet.")
        visible_sessions = sessions[:150]
        self.training_sessions_table.setRowCount(len(visible_sessions))

        for row, session in enumerate(visible_sessions):
            values = [
                session.finished_at[:19] or "-",
                "Ranked Audit" if session.session_mode == "ranked" else "Deathmatch",
                session.weapon_used or "-",
                f"{session.protocol_rate:.1f}%",
                f"{session.kcreds_earned:+d}",
                self.format_duration(session.duration_seconds),
            ]
            for col, value in enumerate(values):
                self.training_sessions_table.setItem(row, col, QTableWidgetItem(str(value)))
        self.training_sessions_table.resizeColumnsToContents()

    def render_training_calendar_grid(self, day_by_date: dict) -> None:
        year = self.current_calendar_month.year
        month = self.current_calendar_month.month
        month_name = self.get_month_name_en(month)
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
            f"Month summary: {monthly_dms} DMs | {self.format_duration(monthly_seconds)} | "
            f"{active_days} active days | average {average_hours:.2f}h per active day"
        )
        self.calendar_goal_label.setText(
            f"Daily goal: {goal_hours:.2f}h | goal reached on {goal_days}/{active_days} days"
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
    def get_month_name_en(month: int) -> str:
        names = {
            1: "January",
            2: "February",
            3: "March",
            4: "April",
            5: "May",
            6: "June",
            7: "July",
            8: "August",
            9: "September",
            10: "October",
            11: "November",
            12: "December",
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
            return f"{current_day.isoformat()}\nNo imported training."
        return (
            f"{current_day.isoformat()}\n"
            f"Training time: {self.format_duration(stats.total_seconds)}\n"
            f"DMs: {stats.dm_count}\n"
            f"Average KD: {stats.average_kd:.2f}\n"
            f"Linked sessions: {stats.linked_sessions}\n"
            f"Weapons: {stats.weapons or '-'}"
        )

    def get_daily_goal_hours(self) -> float:
        return float(self.calendar_settings.get("daily_goal_hours", 2.0))

    def get_calendar_legend_text(self) -> str:
        light = float(self.calendar_settings.get("light_day_hours", 0.5))
        medium = float(self.calendar_settings.get("medium_day_hours", 1.0))
        strong = float(self.calendar_settings.get("strong_day_hours", 2.0))
        goal = self.get_daily_goal_hours()
        return (
            "Legend: gray = no training | "
            f"light blue < {light:.1f}h | medium blue >= {medium:.1f}h | "
            f"strong blue >= {strong:.1f}h | green >= goal {goal:.1f}h"
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

    def import_training_calendar_csv(self) -> None:
        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Training Calendar CSV",
            str(DATA_DIR),
            "CSV (*.csv)",
        )

        if not selected_path:
            return

        import csv
        import shutil

        required_headers = {
            "date",
            "dm_count",
            "total_time",
            "total_hours",
            "average_kd",
            "linked_sessions",
            "average_protocol_rate",
            "weapons",
            "goal_met",
        }

        with open(selected_path, "r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file, delimiter=";")
            headers = set(reader.fieldnames or [])

        if not required_headers.issubset(headers):
            QMessageBox.warning(
                self,
                "Calendar CSV not recognized",
                "The selected CSV does not match the expected Training Calendar export format.",
            )
            return

        target_name = str(self.calendar_settings.get("export_filename") or "training_calendar_month.csv")
        target_path = DATA_DIR / target_name
        shutil.copyfile(selected_path, target_path)
        QMessageBox.information(
            self,
            "Calendar CSV imported",
            f"A validated copy was saved to:\n{target_path}\n\n"
            "The live History calendar still uses local session and imported match data.",
        )

    def export_current_month_calendar(self) -> None:
        days = build_training_calendar()
        year = self.current_calendar_month.year
        month = self.current_calendar_month.month
        monthly_days = [day for day in days if day.date.startswith(f"{year:04d}-{month:02d}")]

        default_name = str(self.calendar_settings.get("export_filename") or "training_calendar_month.csv")
        default_path = DATA_DIR / default_name
        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export current month",
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
                    "yes" if day.total_hours >= goal_hours else "no",
                ])

        QMessageBox.information(self, "Calendar exported", f"Saved to:\n{selected_path}")

    @staticmethod
    def format_duration(seconds: int) -> str:
        seconds = max(int(seconds), 0)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        remaining_seconds = seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"
        return f"{minutes:02d}:{remaining_seconds:02d}"

    def diagonal_mode_label(self, mode: str) -> str:
        return DIAGONAL_RULE_LABELS.get(mode, mode or "-")

    @staticmethod
    def format_protocol_event_line(event: dict) -> str:
        event_type = str(event.get("event_type") or "-")
        rule_name = str(event.get("rule_name") or "-")
        rule_mode = str(event.get("rule_mode") or "-")
        severity = str(event.get("severity") or "-")
        penalized = "yes" if bool(event.get("penalized")) else "no"
        reason = str(event.get("reason") or "-")
        coins_delta = event.get("coins_delta")
        coins_text = ""
        if coins_delta not in (None, ""):
            coins_text = f" | coins {int(coins_delta):+d}"
        return (
            f"{event_type} | {rule_name} | {rule_mode} | {severity} | "
            f"penalized={penalized}{coins_text} | {reason}"
        )

    def refresh_protocol_debug_view(self) -> None:
        mode = self.controller.current_diagonal_rule_mode
        session_mode = self.controller.current_session_mode
        capture_mode = self.controller.capture_mode
        self.protocol_rule_status_label.setText(
            f"Protocol rules: {session_mode} | capture {capture_mode} | diagonal mode {self.diagonal_mode_label(mode)} ({mode})"
        )

        if self.controller.is_session_active and not self.is_debug_view_active():
            return

        debug_lines_max = max(int((self.app_config.input_timing or {}).get("debug_lines_max", 100)), 10)
        events = self.controller.get_live_protocol_events(limit=debug_lines_max)
        if not events:
            self.protocol_debug_text.setPlainText("No protocol events yet.")
            return

        lines = [self.format_protocol_event_line(event) for event in events]
        self.protocol_debug_text.setPlainText("\n".join(lines))

    def refresh_live_stats(self) -> None:
        stats = self.controller.live_stats
        self.clean_hits_label.setText(f"Clean hits: {stats.clean_hits}")
        self.brake_errors_label.setText(f"Counter-strafe errors: {stats.brake_errors}")
        self.diagonal_errors_label.setText(f"Diagonal errors: {stats.diagonal_errors}")
        self.no_ad_errors_label.setText("No A/D (legacy): disabled")
        self.valid_attempts_label.setText(f"Valid attempts: {stats.valid_attempts}")
        self.ignored_clicks_label.setText(f"Ignored clicks: {stats.ignored_clicks}")
        self.current_rate_label.setText(f"Current rate: {stats.protocol_rate:.1f}%")
        if self.controller.current_session_mode == "ranked":
            self.current_kcred_label.setText("Ranked economy: settles at session end")
            if self.controller.is_session_active:
                self.ranked_live_summary_label.setText(
                    f"Ranked Audit Active | Valid attempts: {stats.valid_attempts} | "
                    f"Current rate: {stats.protocol_rate:.1f}% | Protocol events: {stats.protocol_events_total}"
                )
            else:
                self.ranked_live_summary_label.setText("No ranked audit session is active.")
        else:
            self.current_kcred_label.setText(f"Coins this session: +{self.controller.current_session_kcreds}")
            self.ranked_live_summary_label.setText("No ranked audit session is active.")

        input_stats = self.controller.live_input_stats
        self.fire_profile_label.setText(
            f"Fire: tap {input_stats.fire_taps} | "
            f"burst {input_stats.fire_bursts} | "
            f"long spray {input_stats.fire_long_sprays}"
        )
        self.fire_duration_label.setText(
            f"Fire duration: avg {input_stats.average_fire_seconds:.2f}s | "
            f"max {input_stats.max_fire_seconds:.2f}s"
        )
        self.fire_context_label.setText(
            f"W/S shots: {input_stats.shots_while_forward} | "
            f"crouch+fire: {input_stats.shots_with_crouch} | "
            f"long crouch fire: {input_stats.crouch_fire_long_count}"
        )
        self.input_motion_label.setText(
            f"Diagonal: {input_stats.diagonal_entries}x | "
            f"{input_stats.diagonal_seconds:.2f}s"
        )
        self.input_actions_label.setText(
            f"Inputs: keys {input_stats.key_presses} | "
            f"mouse {input_stats.mouse_presses} | "
            f"scroll {input_stats.scroll_events} | "
            f"scroll jump {input_stats.scroll_jump_events}"
        )
        self.refresh_protocol_debug_view()
        if self.is_input_debug_view_active():
            self.refresh_input_debug_view()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self.overlay_window.close()
        if self.controller.is_session_active:
            self.controller.stop_without_saving()
        self._stop_mouse_listener()
        if self.keyboard_listener is not None and self.keyboard_listener.running:
            self.keyboard_listener.stop()
        event.accept()
