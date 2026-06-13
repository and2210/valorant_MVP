from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class InventoryScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Inventory"))

        self.inventory_stack = QStackedWidget()
        self.inventory_buttons: list[QPushButton] = []
        progression_page = self._build_coins_page()
        progression_page.layout().insertWidget(1, self._build_progression_page())
        entries = [
            ("Progression", progression_page),
            ("Weapons", self._build_weapons_page()),
        ]

        buttons_layout = QHBoxLayout()
        for index, (label, widget) in enumerate(entries):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(38)
            button.clicked.connect(
                lambda checked=False, target=index: self._set_subpage(target)
            )
            self.inventory_buttons.append(button)
            buttons_layout.addWidget(button)
            self.inventory_stack.addWidget(widget)

        buttons_layout.addStretch(1)
        root.addLayout(buttons_layout)
        root.addWidget(self.inventory_stack, stretch=1)
        self._set_subpage(0)

    def _set_subpage(self, index: int) -> None:
        self.inventory_stack.setCurrentIndex(index)
        for current, button in enumerate(self.inventory_buttons):
            button.setChecked(current == index)

    def _build_coins_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)

        group = QGroupBox("Coins")
        layout = QGridLayout(group)
        self.balance_label = QLabel("Coins: -")
        self.today_label = QLabel("Today: -")
        self.coins_equipped_label = QLabel("Equipped weapon: -")
        self.coins_next_step_label = QLabel("Next step: -")
        self.inventory_hint_label = QLabel("Wallet details will appear here after the next refresh.")
        self.inventory_hint_label.setWordWrap(True)

        layout.addWidget(self.balance_label, 0, 0)
        layout.addWidget(self.today_label, 0, 1)
        layout.addWidget(self.coins_equipped_label, 1, 0)
        layout.addWidget(self.coins_next_step_label, 1, 1)
        layout.addWidget(self.inventory_hint_label, 2, 0, 1, 2)
        root.addWidget(group)
        root.addStretch(1)
        return page

    def _build_weapons_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)

        summary_group = QGroupBox("Weapons")
        summary_layout = QVBoxLayout(summary_group)
        self.weapons_equipped_label = QLabel("Equipped weapon: -")
        self.available_weapons_label = QLabel("Available weapons: -")
        self.available_weapons_label.setWordWrap(True)
        summary_layout.addWidget(self.weapons_equipped_label)
        summary_layout.addWidget(self.available_weapons_label)
        root.addWidget(summary_group)

        purchase_group = QGroupBox("Weapon Store")
        purchase_layout = QVBoxLayout(purchase_group)
        self.weapon_combo = QComboBox()
        self.weapon_combo.hide()
        self.confirm_purchase_button = QPushButton("Buy All")
        self.confirm_sell_button = QPushButton("Sell Selected")
        self.clear_selection_button = QPushButton("Clear Selection")
        self.store_mode_combo = QComboBox()
        self.store_mode_combo.addItem("Buy", "buy")
        self.store_mode_combo.addItem("Sell", "sell")
        self.store_mode_combo.addItem("Equip", "equip")
        self.purchase_status_label = QLabel("Use the store grid below. Deathmatch pending purchases remain compatible here.")
        self.purchase_status_label.setWordWrap(True)
        self.weapons_empty_label = QLabel("No weapon data is available.")
        self.weapons_empty_label.setWordWrap(True)

        self.weapon_button_widgets: dict[str, QPushButton] = {}
        self.weapon_owned_labels: dict[str, QLabel] = {}
        self.weapon_selected_labels: dict[str, QLabel] = {}
        self.weapon_cost_labels: dict[str, QLabel] = {}
        self.weapon_group_boxes: dict[str, QGroupBox] = {}
        self.weapon_grid_layout = QGridLayout()
        purchase_layout.addWidget(self.store_mode_combo)
        for column, group_name in enumerate(
            ["Sidearms", "SMGs / Shotguns", "Rifles", "Snipers / Heavies"]
        ):
            box = QGroupBox(group_name)
            box_layout = QVBoxLayout(box)
            self.weapon_group_boxes[group_name] = box
            self.weapon_grid_layout.addWidget(box, 0, column)
            setattr(self, f"weapon_group_layout_{column}", box_layout)

        purchase_layout.addWidget(self.weapons_empty_label)
        purchase_layout.addLayout(self.weapon_grid_layout)

        cart_group = QGroupBox("Purchase Cart")
        cart_layout = QVBoxLayout(cart_group)
        self.cart_summary_label = QLabel("Selected weapons: none")
        self.cart_summary_label.setWordWrap(True)
        self.cart_total_label = QLabel("Total cost: 0 Coins")
        self.cart_balance_label = QLabel("Available Coins: -")
        cart_actions = QHBoxLayout()
        cart_actions.addWidget(self.confirm_purchase_button)
        cart_actions.addWidget(self.confirm_sell_button)
        cart_actions.addWidget(self.clear_selection_button)
        cart_actions.addStretch(1)
        cart_layout.addWidget(self.cart_summary_label)
        cart_layout.addWidget(self.cart_total_label)
        cart_layout.addWidget(self.cart_balance_label)
        cart_layout.addLayout(cart_actions)
        purchase_layout.addWidget(cart_group)
        purchase_layout.addWidget(self.purchase_status_label)
        root.addWidget(purchase_group)
        root.addStretch(1)
        return page

    def _build_progression_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)

        dashboard_group = QGroupBox("Progression")
        dashboard_layout = QGridLayout(dashboard_group)
        self.level_label = QLabel("Level: -")
        self.xp_label = QLabel("XP: -")
        self.xp_bar = QProgressBar()
        self.xp_bar.setRange(0, 1000)
        self.xp_bar.setValue(0)
        self.xp_bar.setTextVisible(True)
        self.next_weapon_label = QLabel("Next weapon: -")
        self.total_sessions_label = QLabel("Total sessions: -")
        self.avg_rate_label = QLabel("Average protocol rate: -")
        self.best_weapon_label = QLabel("Best weapon: -")

        dashboard_layout.addWidget(self.level_label, 0, 0)
        dashboard_layout.addWidget(self.xp_label, 0, 1)
        dashboard_layout.addWidget(self.xp_bar, 1, 0, 1, 2)
        dashboard_layout.addWidget(self.next_weapon_label, 2, 0)
        dashboard_layout.addWidget(self.total_sessions_label, 2, 1)
        dashboard_layout.addWidget(self.avg_rate_label, 3, 0)
        dashboard_layout.addWidget(self.best_weapon_label, 3, 1)
        root.addWidget(dashboard_group)
        root.addStretch(1)
        return page
