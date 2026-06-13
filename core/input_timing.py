from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from core.config import AppConfig, FORWARD_KEYS, LATERAL_KEYS, MOVEMENT_KEYS, load_config


@dataclass
class ActiveInputState:
    input_id: str
    action: str
    started_at: float


@dataclass
class InputInterval:
    input_id: str
    action: str
    started_at: float
    finished_at: float
    duration_seconds: float


@dataclass
class RawInputEvent:
    event_index: int
    event_type: str
    input_id: str
    action: str
    windows_timestamp: str
    monotonic_timestamp: float
    duration_seconds: float | None
    active_state: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["monotonic_timestamp"] = round(self.monotonic_timestamp, 6)
        if self.duration_seconds is not None:
            data["duration_seconds"] = round(self.duration_seconds, 4)
        return data


@dataclass
class FireEvaluationContext:
    has_forward_active: bool
    has_lateral_active: bool
    has_diagonal_active: bool
    has_any_movement_active: bool
    forward_released_recently: bool
    within_jump_window: bool
    diagonal_recent_entry: bool
    active_state_snapshot: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InputTimingStats:
    key_presses: int = 0
    useful_key_presses: int = 0
    orphan_key_ups: int = 0
    mouse_presses: int = 0
    lmb_down_count: int = 0
    lmb_up_count: int = 0
    scroll_events: int = 0
    scroll_jump_events: int = 0
    jump_presses: int = 0
    jump_window_events: int = 0
    jump_window_active_seconds: float = 0.0
    jump_strafe_count: int = 0
    jump_strafe_seconds: float = 0.0
    fire_taps: int = 0
    fire_bursts: int = 0
    fire_long_sprays: int = 0
    fire_events: int = 0
    total_fire_seconds: float = 0.0
    max_fire_seconds: float = 0.0
    shots_while_forward: int = 0
    shots_with_crouch: int = 0
    crouch_fire_long_count: int = 0
    crouch_presses: int = 0
    walk_presses: int = 0
    ability_presses: int = 0
    reload_presses: int = 0
    interact_presses: int = 0
    scoreboard_presses: int = 0
    diagonal_entries: int = 0
    diagonal_seconds: float = 0.0
    forward_seconds: float = 0.0
    lateral_seconds: float = 0.0
    active_state_snapshot: dict[str, bool] = field(default_factory=dict)
    action_counts: dict[str, int] = field(default_factory=dict)
    raw_events_total: int = 0
    raw_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def average_fire_seconds(self) -> float:
        if self.fire_events <= 0:
            return 0.0
        return self.total_fire_seconds / self.fire_events

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["average_fire_seconds"] = round(self.average_fire_seconds, 4)
        data["total_fire_seconds"] = round(self.total_fire_seconds, 4)
        data["max_fire_seconds"] = round(self.max_fire_seconds, 4)
        data["diagonal_seconds"] = round(self.diagonal_seconds, 4)
        data["forward_seconds"] = round(self.forward_seconds, 4)
        data["lateral_seconds"] = round(self.lateral_seconds, 4)
        data["jump_window_active_seconds"] = round(self.jump_window_active_seconds, 4)
        data["jump_strafe_seconds"] = round(self.jump_strafe_seconds, 4)
        return data


class InputTimingTracker:
    FORWARD_ACTIONS = {"forward", "backward"}
    LATERAL_ACTIONS = {"left", "right"}
    ABILITY_ACTIONS = {"ability_q", "ability_e", "ability_c", "ultimate", "ability_v", "ability_z"}
    JUMP_ACTIONS = {"jump", "scroll_jump"}
    SCROLL_JUMP_DEBOUNCE_SECONDS = 0.30
    JUMP_WINDOW_SECONDS = 1.50
    PRE_JUMP_GRACE_SECONDS = 0.15
    RECENT_FORWARD_RELEASE_SECONDS = 0.50

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.settings = dict(self.config.input_timing)
        self.capture_mode = self._read_capture_mode()
        self.action_map = self._normalize_action_map(self.settings.get("action_map", {}))
        self.enabled = False
        self.active_state: dict[str, ActiveInputState] = {}
        self.last_release_times: dict[str, float] = {}
        self.intervals: list[InputInterval] = []
        self.raw_events: list[RawInputEvent] | deque[RawInputEvent] = []
        self.raw_events_total = 0
        self.stats = InputTimingStats()
        self.last_state_update = time.monotonic()
        self.diagonal_active = False
        self.last_diagonal_entry_at = 0.0
        self.jump_window_until = 0.0
        self.last_jump_intent_at = 0.0
        self.jump_window_tracked_keys: set[str] = set()
        self._reset_raw_event_buffer()

    def _read_capture_mode(self) -> str:
        mode = str(self.settings.get("capture_mode") or "performance").strip().lower()
        if mode not in {"performance", "full_audit", "off"}:
            return "performance"
        return mode

    def _reset_raw_event_buffer(self) -> None:
        if self.capture_mode == "performance":
            live_max = max(int(self.settings.get("performance_raw_events_live_max", 1000)), 50)
            self.raw_events = deque(maxlen=live_max)
        else:
            self.raw_events = []

    @staticmethod
    def _normalize_action_map(raw_map: dict[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_key, raw_action in raw_map.items():
            key = InputTimingTracker.normalize_input_id(str(raw_key))
            action = str(raw_action or "").strip()
            if key and action:
                normalized[key] = action
        return normalized

    @staticmethod
    def normalize_input_id(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        lower = text.lower()
        if lower.startswith("key."):
            lower = lower[4:]

        aliases = {
            "ctrl_l": "ctrl",
            "ctrl_r": "ctrl",
            "ctrl": "ctrl",
            "shift_l": "shift",
            "shift_r": "shift",
            "shift": "shift",
            "space": "space",
            "tab": "tab",
            "cmd": "cmd",
            "alt_l": "alt",
            "alt_r": "alt",
            "alt": "alt",
            "button.left": "mouse_left",
            "button.right": "mouse_right",
            "button.middle": "mouse_middle",
            "button.x1": "mouse_x1",
            "button.x2": "mouse_x2",
            "mouse.button.left": "mouse_left",
            "mouse.button.right": "mouse_right",
            "mouse.button.middle": "mouse_middle",
            "mouse.button.x1": "mouse_x1",
            "mouse.button.x2": "mouse_x2",
            "`": "grave",
            "'`'": "grave",
            "grave": "grave",
        }

        if lower in aliases:
            return aliases[lower]

        if len(lower) == 1:
            return lower

        return lower

    @staticmethod
    def mouse_button_to_input_id(button: Any) -> str:
        text = str(button).lower()
        if "left" in text:
            return "mouse_left"
        if "right" in text:
            return "mouse_right"
        if "middle" in text:
            return "mouse_middle"
        if "x1" in text:
            return "mouse_x1"
        if "x2" in text:
            return "mouse_x2"
        return InputTimingTracker.normalize_input_id(text)

    def start(self) -> None:
        self.settings = dict(self.config.input_timing)
        self.capture_mode = self._read_capture_mode()
        self.action_map = self._normalize_action_map(self.settings.get("action_map", {}))
        self.reset()
        self.enabled = bool(self.settings.get("enabled", True)) and self.capture_mode != "off"
        self.last_state_update = time.monotonic()

    def stop(self) -> InputTimingStats:
        now = time.monotonic()
        self._update_continuous_state(now)

        for input_id, state in list(self.active_state.items()):
            self._complete_interval(input_id, state.action, state.started_at, now)

        self.active_state.clear()
        self.stats.raw_events_total = int(self.raw_events_total)
        self.stats.raw_events = self.raw_events_to_dicts()
        self.stats.active_state_snapshot = self._active_state_snapshot()
        self.enabled = False
        self.diagonal_active = False
        return self.stats

    def reset(self) -> None:
        self.settings = dict(self.config.input_timing)
        self.capture_mode = self._read_capture_mode()
        self.active_state = {}
        self.last_release_times = {}
        self.intervals = []
        self._reset_raw_event_buffer()
        self.raw_events_total = 0
        self.stats = InputTimingStats()
        self.stats.active_state_snapshot = self._active_state_snapshot()
        self.last_state_update = time.monotonic()
        self.diagonal_active = False
        self.last_diagonal_entry_at = 0.0
        self.jump_window_until = 0.0
        self.last_jump_intent_at = 0.0
        self.jump_window_tracked_keys = set()

    def snapshot(self) -> InputTimingStats:
        if not self.enabled:
            return self.stats

        now = time.monotonic()
        self._update_continuous_state(now)
        self.stats.raw_events_total = int(self.raw_events_total)
        self.stats.raw_events = []
        self.stats.active_state_snapshot = self._active_state_snapshot()
        return self.stats

    def active_input_ids(self) -> set[str]:
        return set(self.active_state)

    def active_actions(self) -> set[str]:
        return {state.action for state in self.active_state.values()}

    def active_state_snapshot(self) -> dict[str, bool]:
        return self._active_state_snapshot()

    def has_forward(self) -> bool:
        return bool(self.active_actions().intersection(self.FORWARD_ACTIONS))

    def has_lateral(self) -> bool:
        return bool(self.active_actions().intersection(self.LATERAL_ACTIONS))

    def has_action(self, action: str) -> bool:
        return action in self.active_actions()

    def is_jump_window_active(self, now: float | None = None) -> bool:
        current_time = time.monotonic() if now is None else now
        return current_time <= self.jump_window_until

    def is_jump_related_window_active(self, now: float | None = None) -> bool:
        current_time = time.monotonic() if now is None else now
        if self.is_jump_window_active(current_time):
            return True
        if self.last_jump_intent_at <= 0:
            return False
        return (self.last_jump_intent_at - self.PRE_JUMP_GRACE_SECONDS) <= current_time <= self.jump_window_until

    def note_jump_window_movement(self, key_name: str, now: float | None = None) -> bool:
        input_id = self.normalize_input_id(key_name)
        if input_id not in MOVEMENT_KEYS:
            return False

        current_time = time.monotonic() if now is None else now
        if not self.is_jump_related_window_active(current_time):
            return False
        if input_id in self.jump_window_tracked_keys:
            return False

        self.jump_window_tracked_keys.add(input_id)
        self.stats.jump_window_events += 1
        return True

    def build_fire_context(self, now: float | None = None) -> FireEvaluationContext:
        current_time = time.monotonic() if now is None else now
        has_forward = self.has_forward()
        has_lateral = self.has_lateral()
        return FireEvaluationContext(
            has_forward_active=has_forward,
            has_lateral_active=has_lateral,
            has_diagonal_active=has_forward and has_lateral,
            has_any_movement_active=has_forward or has_lateral,
            forward_released_recently=self._had_recent_forward_release(current_time),
            within_jump_window=self.is_jump_related_window_active(current_time),
            diagonal_recent_entry=self.last_diagonal_entry_at > 0 and (current_time - self.last_diagonal_entry_at) <= self.PRE_JUMP_GRACE_SECONDS,
            active_state_snapshot=self._active_state_snapshot(),
        )

    def on_key_press(self, raw_key: str) -> None:
        if not self.enabled:
            return

        input_id = self.normalize_input_id(raw_key)
        action = self.action_map.get(input_id)
        if not action:
            return

        now = time.monotonic()
        self._update_continuous_state(now)

        if input_id in self.active_state:
            self._record_raw_event("key_down_repeat", input_id, action, now)
            return

        self.active_state[input_id] = ActiveInputState(input_id=input_id, action=action, started_at=now)
        self._record_raw_event("key_down", input_id, action, now)
        self.stats.key_presses += 1
        self.stats.useful_key_presses += 1
        self._register_action_count(action)
        self.note_jump_window_movement(input_id, now)

    def on_key_release(self, raw_key: str) -> None:
        if not self.enabled:
            return

        input_id = self.normalize_input_id(raw_key)
        action = self.action_map.get(input_id)
        if not action:
            return

        now = time.monotonic()
        self._update_continuous_state(now)

        state = self.active_state.pop(input_id, None)
        if state is None:
            self.stats.orphan_key_ups += 1
            self._record_raw_event("key_up_orphan", input_id, action, now)
            return

        self.jump_window_tracked_keys.discard(input_id)
        self.last_release_times[input_id] = now
        self._record_raw_event("key_up", input_id, action, now, now - state.started_at)
        self._complete_interval(input_id, action, state.started_at, now)

    def on_mouse_button(self, button_name: str, pressed: bool) -> None:
        if not self.enabled:
            return

        input_id = self.normalize_input_id(button_name)
        action = self.action_map.get(input_id)
        if not action:
            return

        now = time.monotonic()
        self._update_continuous_state(now)

        if pressed:
            if input_id in self.active_state:
                self._record_raw_event("mouse_down_repeat", input_id, action, now)
                return

            self.active_state[input_id] = ActiveInputState(input_id=input_id, action=action, started_at=now)
            self._record_raw_event("mouse_down", input_id, action, now)
            self.stats.mouse_presses += 1
            self._register_action_count(action)

            if action == "fire":
                self.stats.lmb_down_count += 1
                if self.has_forward():
                    self.stats.shots_while_forward += 1
                if self.has_action("crouch"):
                    self.stats.shots_with_crouch += 1
            return

        state = self.active_state.pop(input_id, None)
        if state is None:
            self._record_raw_event("mouse_up_orphan", input_id, action, now)
            return

        if action == "fire":
            self.stats.lmb_up_count += 1

        self._record_raw_event("mouse_up", input_id, action, now, now - state.started_at)
        self._complete_interval(input_id, action, state.started_at, now)

    def on_scroll(self, direction: str) -> None:
        if not self.enabled:
            return

        input_id = self.normalize_input_id(direction)
        action = self.action_map.get(input_id)
        if not action:
            return

        now = time.monotonic()
        self._update_continuous_state(now)
        self._record_raw_event("scroll", input_id, action, now)
        self.stats.scroll_events += 1

        if action in self.JUMP_ACTIONS:
            self._register_jump_intent(action, now)
            return

        self._register_action_count(action)

    def raw_events_to_dicts(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.raw_events]

    def _update_continuous_state(self, now: float) -> None:
        elapsed = max(now - self.last_state_update, 0.0)
        if elapsed <= 0:
            self.last_state_update = now
            return

        has_forward = self.has_forward()
        has_lateral = self.has_lateral()

        if has_forward:
            self.stats.forward_seconds += elapsed
        if has_lateral:
            self.stats.lateral_seconds += elapsed
        jump_window_active = self.is_jump_related_window_active(now)
        if has_forward and has_lateral:
            if jump_window_active:
                self.stats.jump_strafe_seconds += elapsed
            else:
                self.stats.diagonal_seconds += elapsed
        if self.is_jump_window_active(now):
            self.stats.jump_window_active_seconds += elapsed

        currently_diagonal = has_forward and has_lateral
        if currently_diagonal and not self.diagonal_active:
            self.last_diagonal_entry_at = now
            if self.is_jump_related_window_active(now):
                self.stats.jump_strafe_count += 1
            else:
                self.stats.diagonal_entries += 1
        self.diagonal_active = currently_diagonal
        self.last_state_update = now

    def _register_action_count(self, action: str) -> None:
        self.stats.action_counts[action] = self.stats.action_counts.get(action, 0) + 1

        if action == "crouch":
            self.stats.crouch_presses += 1
        elif action == "walk":
            self.stats.walk_presses += 1
        elif action in self.ABILITY_ACTIONS:
            self.stats.ability_presses += 1
        elif action == "reload":
            self.stats.reload_presses += 1
        elif action == "interact":
            self.stats.interact_presses += 1
        elif action == "scoreboard":
            self.stats.scoreboard_presses += 1

    def _register_jump_intent(self, action: str, now: float) -> bool:
        debounce_seconds = float(
            self.settings.get("scroll_jump_debounce_seconds", self.SCROLL_JUMP_DEBOUNCE_SECONDS)
        )
        if debounce_seconds <= 0:
            debounce_seconds = self.SCROLL_JUMP_DEBOUNCE_SECONDS

        if self.last_jump_intent_at > 0 and (now - self.last_jump_intent_at) < debounce_seconds:
            self.jump_window_until = max(self.jump_window_until, now + self.JUMP_WINDOW_SECONDS)
            return False

        self.last_jump_intent_at = now
        self.jump_window_until = now + self.JUMP_WINDOW_SECONDS
        self.stats.scroll_jump_events += 1
        self.stats.jump_presses += 1
        self.stats.action_counts[action] = self.stats.action_counts.get(action, 0) + 1
        return True

    def _record_raw_event(
        self,
        event_type: str,
        input_id: str,
        action: str,
        monotonic_timestamp: float,
        duration_seconds: float | None = None,
    ) -> None:
        self.raw_events_total += 1
        event = RawInputEvent(
            event_index=self.raw_events_total,
            event_type=event_type,
            input_id=input_id,
            action=action,
            windows_timestamp=datetime.now().isoformat(timespec="milliseconds"),
            monotonic_timestamp=monotonic_timestamp,
            duration_seconds=duration_seconds,
            active_state=self._active_state_snapshot(),
        )
        self.raw_events.append(event)
        self.stats.raw_events_total = int(self.raw_events_total)
        self.stats.active_state_snapshot = dict(event.active_state)

    def _complete_interval(self, input_id: str, action: str, started_at: float, finished_at: float) -> None:
        duration = max(finished_at - started_at, 0.0)
        interval = InputInterval(
            input_id=input_id,
            action=action,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
        )
        self.intervals.append(interval)

        if action == "fire":
            self._register_fire_interval(interval)

    def _register_fire_interval(self, interval: InputInterval) -> None:
        duration = interval.duration_seconds
        tap_max = float(self.settings.get("tap_max_seconds", 0.12))
        burst_max = float(self.settings.get("burst_max_seconds", 0.50))
        crouch_fire_max = float(self.settings.get("crouch_fire_max_seconds", 0.50))

        self.stats.fire_events += 1
        self.stats.total_fire_seconds += duration
        self.stats.max_fire_seconds = max(self.stats.max_fire_seconds, duration)

        if duration <= tap_max:
            self.stats.fire_taps += 1
        elif duration <= burst_max:
            self.stats.fire_bursts += 1
        else:
            self.stats.fire_long_sprays += 1

        crouch_overlap = self._calculate_overlap_with_action(interval.started_at, interval.finished_at, "crouch")
        if crouch_overlap > crouch_fire_max:
            self.stats.crouch_fire_long_count += 1

    def _calculate_overlap_with_action(self, started_at: float, finished_at: float, action: str) -> float:
        total = 0.0

        for interval in self.intervals:
            if interval.action != action:
                continue
            start = max(started_at, interval.started_at)
            end = min(finished_at, interval.finished_at)
            if end > start:
                total += end - start

        now = time.monotonic()
        for state in self.active_state.values():
            if state.action != action:
                continue
            start = max(started_at, state.started_at)
            end = min(finished_at, now)
            if end > start:
                total += end - start

        return total

    def _had_recent_forward_release(self, current_time: float) -> bool:
        for key_name in FORWARD_KEYS:
            released_at = self.last_release_times.get(key_name, 0.0)
            if released_at > 0 and (current_time - released_at) < self.RECENT_FORWARD_RELEASE_SECONDS:
                return True
        return False

    def _active_state_snapshot(self) -> dict[str, bool]:
        active_ids = set(self.active_state)
        return {
            "w": "w" in active_ids,
            "a": "a" in active_ids,
            "s": "s" in active_ids,
            "d": "d" in active_ids,
            "ctrl": "ctrl" in active_ids,
            "shift": "shift" in active_ids,
            "mouse_left": "mouse_left" in active_ids,
        }
