from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from core.config import AppConfig, load_config


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
    session_active: bool
    session_ref: str
    session_mode: str
    training_method: str
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
class InputTimingStats:
    key_presses: int = 0
    mouse_presses: int = 0
    scroll_events: int = 0
    scroll_jump_events: int = 0
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
    jump_presses: int = 0
    ability_presses: int = 0
    reload_presses: int = 0
    interact_presses: int = 0
    scoreboard_presses: int = 0
    diagonal_entries: int = 0
    diagonal_seconds: float = 0.0
    forward_seconds: float = 0.0
    lateral_seconds: float = 0.0
    wasd_seconds: float = 0.0
    shift_seconds: float = 0.0
    ctrl_seconds: float = 0.0
    raw_event_count: int = 0
    raw_events_total: int = 0
    useful_key_presses: int = 0
    lmb_clicks: int = 0
    lmb_down_count: int = 0
    lmb_up_count: int = 0
    orphan_key_ups: int = 0
    possible_crouch_sprays: int = 0
    jump_window_events: int = 0
    jump_window_active_seconds: float = 0.0
    active_state_snapshot: dict[str, bool] = field(default_factory=dict)
    action_counts: dict[str, int] = field(default_factory=dict)

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
        data["wasd_seconds"] = round(self.wasd_seconds, 4)
        data["shift_seconds"] = round(self.shift_seconds, 4)
        data["ctrl_seconds"] = round(self.ctrl_seconds, 4)
        data["jump_window_active_seconds"] = round(self.jump_window_active_seconds, 4)
        return data


class InputTimingTracker:
    """
    Gravador de timing de input.

    Esta classe mede comandos enviados pelo jogador. Ela não tenta ler o estado
    interno do Valorant. Exemplo: se Ctrl foi pressionado, registramos comando
    de crouch; se o personagem realmente agachou depende do jogo, mas para
    análise de padrão motor o comando é suficiente.
    """

    FORWARD_ACTIONS = {"forward", "backward"}
    LATERAL_ACTIONS = {"left", "right"}
    ABILITY_ACTIONS = {"ability_q", "ability_e", "ability_c", "ultimate", "ability_v", "ability_z"}
    JUMP_ACTIONS = {"jump", "scroll_jump"}
    SCROLL_JUMP_DEBOUNCE_SECONDS = 0.30
    JUMP_WINDOW_SECONDS = 1.50

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.settings = dict(self.config.input_timing)
        self.action_map = self._normalize_action_map(self.settings.get("action_map", {}))
        self.enabled = False
        self.active_inputs: dict[str, tuple[str, float]] = {}
        self.intervals: list[InputInterval] = []
        self.raw_events: list[RawInputEvent] = []
        self.stats = InputTimingStats()
        self.last_state_update = time.monotonic()
        self.diagonal_active = False
        self.session_ref = ""
        self.session_mode = "dm_training"
        self.training_method = ""
        self.jump_window_until = 0.0
        self.last_jump_intent_at = 0.0
        self.jump_window_tracked_keys: set[str] = set()

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

    def start(
        self,
        session_ref: str = "",
        session_mode: str = "dm_training",
        training_method: str = "",
    ) -> None:
        self.reset()
        self.enabled = bool(self.settings.get("enabled", True))
        self.last_state_update = time.monotonic()
        self.session_ref = str(session_ref or "")
        self.session_mode = str(session_mode or "dm_training")
        self.training_method = str(training_method or "")

    def stop(self) -> InputTimingStats:
        now = time.monotonic()
        self._update_continuous_state(now)

        # Fecha intervalos ainda ativos no encerramento da sessão, sem presumir
        # soltura física das teclas.
        for input_id, (action, started_at) in list(self.active_inputs.items()):
            self._complete_interval(input_id, action, started_at, now)

        self.active_inputs.clear()
        self.stats.active_state_snapshot = self._active_state_snapshot()
        self.enabled = False
        self.diagonal_active = False
        return self.stats

    def reset(self) -> None:
        self.active_inputs = {}
        self.intervals = []
        self.raw_events = []
        self.stats = InputTimingStats()
        self.stats.active_state_snapshot = self._active_state_snapshot()
        self.last_state_update = time.monotonic()
        self.diagonal_active = False
        self.jump_window_until = 0.0
        self.last_jump_intent_at = 0.0
        self.jump_window_tracked_keys = set()

    def snapshot(self) -> InputTimingStats:
        if not self.enabled:
            return self.stats

        now = time.monotonic()
        self._update_continuous_state(now)
        return self.stats

    def active_actions(self) -> set[str]:
        return {action for action, _started_at in self.active_inputs.values()}

    def active_input_ids(self) -> set[str]:
        return set(self.active_inputs)

    def has_forward(self) -> bool:
        return bool(self.active_actions().intersection(self.FORWARD_ACTIONS))

    def has_lateral(self) -> bool:
        return bool(self.active_actions().intersection(self.LATERAL_ACTIONS))

    def has_action(self, action: str) -> bool:
        return action in self.active_actions()

    def is_jump_window_active(self, now: float | None = None) -> bool:
        current_time = time.monotonic() if now is None else now
        return current_time <= self.jump_window_until

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
        if has_forward and has_lateral:
            self.stats.diagonal_seconds += elapsed
        if self.active_input_ids().intersection({"w", "a", "s", "d"}):
            self.stats.wasd_seconds += elapsed
        if self.has_action("walk"):
            self.stats.shift_seconds += elapsed
        if self.has_action("crouch"):
            self.stats.ctrl_seconds += elapsed
        if self.is_jump_window_active(now):
            self.stats.jump_window_active_seconds += elapsed

        currently_diagonal = has_forward and has_lateral
        if currently_diagonal and not self.diagonal_active:
            self.stats.diagonal_entries += 1
        self.diagonal_active = currently_diagonal
        self.last_state_update = now

    def _register_action_count(self, action: str) -> None:
        self.stats.action_counts[action] = self.stats.action_counts.get(action, 0) + 1

        if action == "crouch":
            self.stats.crouch_presses += 1
        elif action == "walk":
            self.stats.walk_presses += 1
        elif action == "jump":
            self.stats.jump_presses += 1
        elif action in self.ABILITY_ACTIONS:
            self.stats.ability_presses += 1
        elif action == "reload":
            self.stats.reload_presses += 1
        elif action == "interact":
            self.stats.interact_presses += 1
        elif action == "scoreboard":
            self.stats.scoreboard_presses += 1

    def _active_state_snapshot(self) -> dict[str, bool]:
        active = self.active_input_ids()
        return {
            "w": "w" in active,
            "a": "a" in active,
            "s": "s" in active,
            "d": "d" in active,
            "ctrl": "ctrl" in active,
            "shift": "shift" in active,
        }

    def _record_raw_event(
        self,
        event_type: str,
        input_id: str,
        action: str,
        monotonic_timestamp: float,
        duration_seconds: float | None = None,
    ) -> None:
        event = RawInputEvent(
            event_index=len(self.raw_events) + 1,
            event_type=event_type,
            input_id=input_id,
            action=action,
            session_active=self.enabled,
            session_ref=self.session_ref,
            session_mode=self.session_mode,
            training_method=self.training_method,
            windows_timestamp=datetime.now().isoformat(timespec="milliseconds"),
            monotonic_timestamp=monotonic_timestamp,
            duration_seconds=duration_seconds,
            active_state=self._active_state_snapshot(),
        )
        self.raw_events.append(event)
        self.stats.raw_event_count = len(self.raw_events)
        self.stats.raw_events_total = len(self.raw_events)
        self.stats.active_state_snapshot = dict(event.active_state)

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

    def note_jump_window_movement(self, key_name: str, now: float | None = None) -> bool:
        input_id = self.normalize_input_id(key_name)
        if input_id not in {"w", "a", "s", "d"}:
            return False

        current_time = time.monotonic() if now is None else now
        if not self.is_jump_window_active(current_time):
            return False
        if input_id in self.jump_window_tracked_keys:
            return False

        self.jump_window_tracked_keys.add(input_id)
        self.stats.jump_window_events += 1
        return True

    def on_key_press(self, raw_key: str) -> None:
        if not self.enabled:
            return None

        input_id = self.normalize_input_id(raw_key)
        action = self.action_map.get(input_id)
        if not action:
            return None

        if input_id in self.active_inputs:
            return None

        now = time.monotonic()
        self._update_continuous_state(now)
        self.active_inputs[input_id] = (action, now)
        self._record_raw_event("key_down", input_id, action, now)
        self.stats.key_presses += 1
        self.stats.useful_key_presses += 1
        self._register_action_count(action)
        return None

    def on_key_release(self, raw_key: str) -> None:
        if not self.enabled:
            return

        input_id = self.normalize_input_id(raw_key)
        if input_id not in self.active_inputs:
            action = self.action_map.get(input_id, "")
            if action:
                now = time.monotonic()
                self._update_continuous_state(now)
                self.stats.orphan_key_ups += 1
                self._record_raw_event("key_up_orphan", input_id, action, now)
            return

        now = time.monotonic()
        self._update_continuous_state(now)
        action, started_at = self.active_inputs.pop(input_id)
        self.jump_window_tracked_keys.discard(input_id)
        self._record_raw_event("key_up", input_id, action, now, now - started_at)
        self._complete_interval(input_id, action, started_at, now)

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
            if input_id in self.active_inputs:
                return

            self.active_inputs[input_id] = (action, now)
            self._record_raw_event("mouse_down", input_id, action, now)
            self.stats.mouse_presses += 1
            self._register_action_count(action)

            if action == "fire":
                self.stats.lmb_clicks += 1
                self.stats.lmb_down_count += 1
                if self.has_forward():
                    self.stats.shots_while_forward += 1
                if self.has_action("crouch"):
                    self.stats.shots_with_crouch += 1
            return

        if input_id not in self.active_inputs:
            return

        stored_action, started_at = self.active_inputs.pop(input_id)
        if stored_action == "fire":
            self.stats.lmb_up_count += 1
        self._record_raw_event("mouse_up", input_id, stored_action, now, now - started_at)
        self._complete_interval(input_id, stored_action, started_at, now)

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
        if crouch_overlap > 0:
            if self.stats.shots_with_crouch <= 0 or not self.has_action("crouch"):
                # Evita perder casos em que o crouch começou depois do tiro.
                self.stats.shots_with_crouch += 1
            if crouch_overlap > crouch_fire_max:
                self.stats.crouch_fire_long_count += 1
            if self._has_crouch_spray_pattern(interval, crouch_fire_max):
                self.stats.possible_crouch_sprays += 1

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
        for active_action, active_started_at in self.active_inputs.values():
            if active_action != action:
                continue
            start = max(started_at, active_started_at)
            end = min(finished_at, now)
            if end > start:
                total += end - start

        return total

    def _has_crouch_spray_pattern(self, fire_interval: InputInterval, crouch_window: float) -> bool:
        crouch_starts: list[float] = []

        for interval in self.intervals:
            if interval.action != "crouch":
                continue
            if interval.finished_at > fire_interval.started_at and interval.started_at < fire_interval.finished_at:
                crouch_starts.append(interval.started_at)

        for active_action, active_started_at in self.active_inputs.values():
            if active_action == "crouch" and active_started_at < fire_interval.finished_at:
                crouch_starts.append(active_started_at)

        if not crouch_starts:
            return False

        if fire_interval.duration_seconds > crouch_window:
            return True

        return any(abs(started_at - fire_interval.started_at) <= crouch_window for started_at in crouch_starts)

    def raw_events_to_dicts(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.raw_events]
