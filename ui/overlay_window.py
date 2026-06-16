from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class OverlayWindow(QWidget):
    UPDATE_INTERVAL_MS = 150
    SCROLL_HIGHLIGHT_TICKS = 4
    INPUT_PULSE_TICKS = 3

    def __init__(
        self,
        state_provider: Callable[[], dict[str, Any]],
        position_changed: Callable[[int, int], None] | None = None,
    ) -> None:
        super().__init__(None)
        self.state_provider = state_provider
        self.position_changed = position_changed
        self.settings: dict[str, Any] = {}
        self.key_labels: dict[str, QLabel] = {}
        self._last_rendered: dict[str, Any] = {}
        self._last_scroll_events = 0
        self._last_scroll_jump_events = 0
        self._last_event_counts_by_input: dict[str, int] = {}
        self._input_pulse_ticks: dict[str, int] = {}
        self._scroll_ticks = 0
        self._scroll_jump_ticks = 0
        self._last_refresh_monotonic = 0.0
        self._drag_offset: QPoint | None = None
        self._drag_started = False

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._build_ui()

        self.timer = QTimer(self)
        self.timer.setInterval(self.UPDATE_INTERVAL_MS)
        self.timer.timeout.connect(self.refresh_state)
        self.timer.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.panel = QFrame()
        self.panel.setObjectName("OverlayPanel")
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(12, 10, 12, 10)
        panel_layout.setSpacing(6)

        status_row = QHBoxLayout()
        self.session_dot = QLabel("●")
        self.session_label = QLabel("Session: OFF")
        self.mode_label = QLabel("Mode: Deathmatch")
        self.body_state_label = QLabel("State: idle")
        status_row.addWidget(self.session_dot)
        status_row.addWidget(self.session_label)
        status_row.addStretch(1)
        panel_layout.addLayout(status_row)
        panel_layout.addWidget(self.mode_label)
        panel_layout.addWidget(self.body_state_label)

        keys = QGridLayout()
        keys.setHorizontalSpacing(4)
        keys.setVerticalSpacing(4)
        self._add_key(keys, "w", "W", 0, 1)
        self._add_key(keys, "a", "A", 1, 0)
        self._add_key(keys, "s", "S", 1, 1)
        self._add_key(keys, "d", "D", 1, 2)
        panel_layout.addLayout(keys)

        modifiers = QHBoxLayout()
        for key, text in (("shift", "Shift"), ("ctrl", "Ctrl")):
            label = self._make_key_label(text)
            self.key_labels[key] = label
            modifiers.addWidget(label)
        panel_layout.addLayout(modifiers)

        mouse_row = QHBoxLayout()
        for key, text in (
            ("mouse_left", "LMB"),
            ("jump", "Jump"),
        ):
            label = self._make_key_label(text)
            self.key_labels[key] = label
            mouse_row.addWidget(label)
        panel_layout.addLayout(mouse_row)

        self.compact_status_label = QLabel("Ready")
        panel_layout.addWidget(self.compact_status_label)
        root.addWidget(self.panel)

    def _add_key(
        self,
        layout: QGridLayout,
        key: str,
        text: str,
        row: int,
        column: int,
    ) -> None:
        label = self._make_key_label(text)
        self.key_labels[key] = label
        layout.addWidget(label, row, column)

    @staticmethod
    def _make_key_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("pressed", False)
        return label

    def apply_settings(self, settings: dict[str, Any]) -> None:
        self.settings = dict(settings)
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if bool(self.settings.get("overlay_always_on_top", True)):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if bool(self.settings.get("overlay_click_through", False)):
            flags |= Qt.WindowType.WindowTransparentForInput

        self.hide()
        self.setWindowFlags(flags)
        self.setWindowOpacity(float(self.settings.get("overlay_opacity", 0.85)))
        self._apply_scale(float(self.settings.get("overlay_scale", 1.0)))
        self.compact_status_label.setVisible(
            not bool(self.settings.get("overlay_minimal_mode", False))
        )
        self.adjustSize()
        self.move_to_configured_position()

        if bool(self.settings.get("overlay_enabled", False)):
            self.show()
            self.raise_()

    def _apply_scale(self, scale: float) -> None:
        font_size = max(int(round(12 * scale)), 9)
        key_height = max(int(round(28 * scale)), 22)
        key_width = max(int(round(42 * scale)), 32)
        self.setStyleSheet(
            f"""
            QFrame#OverlayPanel {{
                background-color: rgba(12, 16, 24, 225);
                border: 1px solid rgba(148, 163, 184, 110);
                border-radius: 8px;
            }}
            QLabel {{
                color: #E5E7EB;
                font-size: {font_size}px;
            }}
            QLabel[pressed="false"] {{
                background-color: rgba(51, 65, 85, 210);
                border: 1px solid rgba(148, 163, 184, 100);
                border-radius: 4px;
                min-width: {key_width}px;
                min-height: {key_height}px;
            }}
            QLabel[pressed="true"] {{
                background-color: rgba(34, 197, 94, 230);
                color: #07110A;
                border: 1px solid #86EFAC;
                border-radius: 4px;
                min-width: {key_width}px;
                min-height: {key_height}px;
                font-weight: bold;
            }}
            """
        )

    def refresh_state(self) -> None:
        if not self.isVisible():
            return
        self._last_refresh_monotonic = time.monotonic()
        snapshot = self.state_provider()
        scroll_events = int(snapshot.get("scroll_events", 0))
        scroll_jump_events = int(snapshot.get("scroll_jump_events", 0))
        if scroll_events > self._last_scroll_events:
            self._scroll_ticks = self.SCROLL_HIGHLIGHT_TICKS
        if scroll_jump_events > self._last_scroll_jump_events:
            self._scroll_jump_ticks = self.SCROLL_HIGHLIGHT_TICKS
        self._last_scroll_events = scroll_events
        self._last_scroll_jump_events = scroll_jump_events
        event_counts = dict(snapshot.get("event_counts_by_input") or {})
        for key in ("w", "a", "s", "d", "shift", "ctrl", "mouse_left"):
            current_count = int(event_counts.get(key, 0))
            if current_count > int(self._last_event_counts_by_input.get(key, 0)):
                self._input_pulse_ticks[key] = self.INPUT_PULSE_TICKS
            self._last_event_counts_by_input[key] = current_count
        jump_count = (
            int(event_counts.get("space", 0))
            + int(event_counts.get("scroll_up", 0))
            + int(event_counts.get("scroll_down", 0))
        )
        if jump_count > int(self._last_event_counts_by_input.get("jump", 0)):
            self._input_pulse_ticks["jump"] = self.INPUT_PULSE_TICKS
        self._last_event_counts_by_input["jump"] = jump_count

        render_state = {
            "session_active": bool(snapshot.get("session_active", False)),
            "session_mode": str(snapshot.get("session_mode") or "deathmatch"),
            "input_state": dict(snapshot.get("input_state") or {}),
            "training_state": dict(snapshot.get("training_state") or {}),
            "input_pulses": dict(self._input_pulse_ticks),
            "scroll_active": self._scroll_ticks > 0,
            "scroll_jump_active": self._scroll_jump_ticks > 0,
        }
        if render_state != self._last_rendered:
            self._render(render_state)
            self._last_rendered = render_state

        self._scroll_ticks = max(self._scroll_ticks - 1, 0)
        self._scroll_jump_ticks = max(self._scroll_jump_ticks - 1, 0)
        for key, ticks in list(self._input_pulse_ticks.items()):
            next_ticks = max(int(ticks) - 1, 0)
            if next_ticks:
                self._input_pulse_ticks[key] = next_ticks
            else:
                self._input_pulse_ticks.pop(key, None)

    def _render(self, state: dict[str, Any]) -> None:
        active = bool(state["session_active"])
        mode = str(state["session_mode"])
        mode_label = "Ranked" if mode == "ranked" else "Deathmatch"
        status = "Ranked audit" if mode == "ranked" else "Deathmatch Coins"
        if not active:
            status = "Ready"

        self.session_dot.setStyleSheet(
            f"color: {'#22C55E' if active else '#EF4444'}; background: transparent;"
        )
        self.session_label.setText(f"Session: {'ON' if active else 'OFF'}")
        self.mode_label.setText(f"Mode: {mode_label}")
        training_state = dict(state.get("training_state") or {})
        body_state = str(training_state.get("body_state") or "idle")
        self.body_state_label.setText(f"State: {body_state}")
        self.compact_status_label.setText(status)

        input_state = dict(state["input_state"])
        input_pulses = dict(state["input_pulses"])
        for key in ("w", "a", "s", "d", "shift", "ctrl", "mouse_left"):
            self._set_pressed(
                self.key_labels[key],
                bool(input_state.get(key, False)) or int(input_pulses.get(key, 0)) > 0,
            )
        jump_pressed = (
            bool(input_state.get("space", False))
            or bool(state["scroll_active"])
            or bool(state["scroll_jump_active"])
            or int(input_pulses.get("jump", 0)) > 0
        )
        self._set_pressed(self.key_labels["jump"], jump_pressed)

    def _set_pressed(self, label: QLabel, pressed: bool) -> None:
        if bool(label.property("pressed")) == pressed:
            return
        label.setProperty("pressed", pressed)
        label.style().unpolish(label)
        label.style().polish(label)

    def last_refresh_age_ms(self) -> int | None:
        if self._last_refresh_monotonic <= 0:
            return None
        return int(round((time.monotonic() - self._last_refresh_monotonic) * 1000))

    def move_to_configured_position(self) -> None:
        if str(self.settings.get("overlay_position") or "") == "custom":
            x = self.settings.get("overlay_custom_x")
            y = self.settings.get("overlay_custom_y")
            if x is not None and y is not None:
                try:
                    self.move(int(x), int(y))
                    return
                except (TypeError, ValueError):
                    pass
        self.move_to_preset(str(self.settings.get("overlay_position", "top_right")))

    def move_to_preset(self, position: str) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        margin = 18
        width = self.sizeHint().width()
        height = self.sizeHint().height()
        positions = {
            "top_left": QPoint(area.left() + margin, area.top() + margin),
            "top_right": QPoint(area.right() - width - margin, area.top() + margin),
            "bottom_left": QPoint(area.left() + margin, area.bottom() - height - margin),
            "bottom_right": QPoint(
                area.right() - width - margin,
                area.bottom() - height - margin,
            ),
            "center_top": QPoint(
                area.center().x() - width // 2,
                area.top() + margin,
            ),
        }
        self.move(positions.get(position, positions["top_right"]))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not bool(self.settings.get("overlay_click_through", False))
        ):
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_started = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_started
            and not bool(self.settings.get("overlay_click_through", False))
            and self.position_changed is not None
        ):
            point = self.pos()
            self.position_changed(int(point.x()), int(point.y()))
        self._drag_offset = None
        self._drag_started = False
        super().mouseReleaseEvent(event)
