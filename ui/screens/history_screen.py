from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


class HistoryScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()

        root = QVBoxLayout(self)
        root.addWidget(QLabel("History"))

        self.history_stack = QStackedWidget()
        self.history_buttons: list[QPushButton] = []
        tracker_page = self._build_tracker_page()
        training_page = self._build_training_sessions_page()
        training_page.layout().addWidget(tracker_page)
        entries = [
            ("Calendar", self._build_calendar_page()),
            ("Training Sessions", training_page),
            ("Ranked Matches", self._build_ranked_page()),
        ]

        buttons_layout = QHBoxLayout()
        for index, (label, widget) in enumerate(entries):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(38)
            button.clicked.connect(
                lambda checked=False, target=index: self._set_subpage(target)
            )
            self.history_buttons.append(button)
            buttons_layout.addWidget(button)
            self.history_stack.addWidget(widget)

        buttons_layout.addStretch(1)
        root.addLayout(buttons_layout)
        root.addWidget(self.history_stack, stretch=1)
        self._set_subpage(0)

    def _set_subpage(self, index: int) -> None:
        self.history_stack.setCurrentIndex(index)
        for current, button in enumerate(self.history_buttons):
            button.setChecked(current == index)

    def _build_calendar_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)

        calendar_group = QGroupBox("Training Calendar")
        calendar_layout = QVBoxLayout(calendar_group)

        calendar_actions = QHBoxLayout()
        self.prev_month_button = QPushButton("◀ Previous month")
        self.calendar_month_label = QLabel("-")
        self.calendar_month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.today_month_button = QPushButton("Current month")
        self.next_month_button = QPushButton("Next month ▶")
        calendar_actions.addWidget(self.prev_month_button)
        calendar_actions.addWidget(self.calendar_month_label, stretch=1)
        calendar_actions.addWidget(self.today_month_button)
        calendar_actions.addWidget(self.next_month_button)
        calendar_layout.addLayout(calendar_actions)

        self.calendar_month_summary_label = QLabel("Month summary: -")
        self.calendar_goal_label = QLabel("Daily goal: -")
        calendar_layout.addWidget(self.calendar_month_summary_label)
        calendar_layout.addWidget(self.calendar_goal_label)

        self.training_calendar_table = QTableWidget(6, 7)
        self.training_calendar_table.setHorizontalHeaderLabels(
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        )
        self.training_calendar_table.setVerticalHeaderLabels(["1", "2", "3", "4", "5", "6"])
        self.training_calendar_table.setMinimumHeight(260)
        self.training_calendar_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.training_calendar_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.training_calendar_table.setWordWrap(True)
        calendar_layout.addWidget(self.training_calendar_table)

        self.calendar_legend_label = QLabel("Legend: -")
        calendar_layout.addWidget(self.calendar_legend_label)
        root.addWidget(calendar_group, stretch=1)
        return page

    def _build_tracker_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)

        actions = QHBoxLayout()
        self.import_tracker_button = QPushButton("Import Deathmatches")
        self.import_all_tracker_checkbox = QCheckBox("Import all within the limit")
        self.import_all_tracker_checkbox.setChecked(True)
        self.import_day_button = QPushButton("Refresh day")
        self.import_range_button = QPushButton("Refresh range")
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
        actions.addWidget(QLabel("From:"))
        actions.addWidget(self.import_from_date)
        actions.addWidget(QLabel("To:"))
        actions.addWidget(self.import_to_date)
        actions.addWidget(self.import_day_button)
        actions.addWidget(self.import_range_button)
        actions.addStretch(1)

        tracker_group = QGroupBox("Map Tracking")
        tracker_layout = QGridLayout(tracker_group)
        self.tracker_total_label = QLabel("Imported DMs: 0")
        self.tracker_kd_label = QLabel("Average KD: -")
        self.tracker_best_map_label = QLabel("Best map: -")
        self.tracker_best_agent_label = QLabel("Best agent: -")
        self.tracker_best_match_label = QLabel("Best DM: -")
        self.tracker_last_match_label = QLabel("Latest DM: -")

        tracker_layout.addWidget(self.tracker_total_label, 0, 0)
        tracker_layout.addWidget(self.tracker_kd_label, 0, 1)
        tracker_layout.addWidget(self.tracker_best_map_label, 1, 0)
        tracker_layout.addWidget(self.tracker_best_agent_label, 1, 1)
        tracker_layout.addWidget(self.tracker_best_match_label, 2, 0)
        tracker_layout.addWidget(self.tracker_last_match_label, 2, 1)
        root.addWidget(tracker_group)

        self.tracker_status_label = QLabel("No imported Deathmatches yet.")
        root.addWidget(self.tracker_status_label)

        self.tracker_table = QTableWidget(0, 10)
        self.tracker_table.setHorizontalHeaderLabels(
            ["Date", "Map", "Agent", "K", "D", "A", "KD", "Duration", "Weapon", "Protocol"]
        )
        self.tracker_table.setMinimumHeight(260)
        root.addWidget(self.tracker_table, stretch=1)
        return page

    def _build_training_sessions_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        self.training_sessions_summary_label = QLabel("Training sessions: -")
        self.training_sessions_status_label = QLabel("No saved sessions yet.")
        root.addWidget(self.training_sessions_summary_label)
        root.addWidget(self.training_sessions_status_label)
        self.training_sessions_table = QTableWidget(0, 6)
        self.training_sessions_table.setHorizontalHeaderLabels(
            ["Date", "Mode", "Weapon", "Rate", "Coins", "Duration"]
        )
        self.training_sessions_table.setMinimumHeight(320)
        root.addWidget(self.training_sessions_table, stretch=1)
        return page

    def _build_ranked_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)

        actions = QHBoxLayout()
        self.import_ranked_button = QPushButton("Import Ranked Matches")
        self.import_all_ranked_checkbox = QCheckBox("Import all within the limit")
        self.import_all_ranked_checkbox.setChecked(True)
        self.import_ranked_day_button = QPushButton("Refresh day")
        self.import_ranked_range_button = QPushButton("Refresh range")
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
        actions.addWidget(QLabel("From:"))
        actions.addWidget(self.ranked_from_date)
        actions.addWidget(QLabel("To:"))
        actions.addWidget(self.ranked_to_date)
        actions.addWidget(self.import_ranked_day_button)
        actions.addWidget(self.import_ranked_range_button)
        actions.addStretch(1)

        summary_group = QGroupBox("Ranked Matches")
        summary_layout = QGridLayout(summary_group)
        self.ranked_total_label = QLabel("Ranked matches: 0")
        self.ranked_winrate_label = QLabel("Win rate: -")
        self.ranked_rr_label = QLabel("RR: -")
        self.ranked_acs_label = QLabel("Average ACS: -")
        self.ranked_adr_label = QLabel("Average ADR: -")
        self.ranked_dd_label = QLabel("DDΔ: -")
        self.ranked_fbfd_label = QLabel("FB/FD: -")
        self.ranked_kast_label = QLabel("Average KAST: -")
        self.ranked_signal_label = QLabel("Dominant signal: -")
        self.ranked_focus_label = QLabel("Recommended focus: -")
        self.ranked_best_map_label = QLabel("Best map: -")
        self.ranked_worst_map_label = QLabel("Worst map: -")

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

        self.ranked_history_status_label = QLabel("No imported ranked matches yet.")
        root.addWidget(self.ranked_history_status_label)

        self.ranked_table = QTableWidget(0, 14)
        self.ranked_table.setHorizontalHeaderLabels(
            [
                "Date",
                "Map",
                "Agent",
                "Result",
                "Rank",
                "RRΔ",
                "ACS",
                "ADR",
                "DDΔ",
                "DD/R",
                "FB",
                "FD",
                "FB-FD",
                "K/D/A",
            ]
        )
        self.ranked_table.setMinimumHeight(360)
        root.addWidget(self.ranked_table, stretch=1)
        return page
