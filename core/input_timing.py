from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
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

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.settings = dict(self.config.input_timing)
        self.action_map = self._normalize_action_map(self.settings.get("action_map", {}))
        self.enabled = False
        self.active_inputs: dict[str, tuple[str, float]] = {}
        self.intervals: list[InputInterval] = []
        self.stats = InputTimingStats()
        self.last_state_update = time.monotonic()
        self.diagonal_active = False

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
        self.reset()
        self.enabled = bool(self.settings.get("enabled", True))
        self.last_state_update = time.monotonic()

    def stop(self) -> InputTimingStats:
        now = time.monotonic()
        self._update_continuous_state(now)

        # Fecha intervalos ainda ativos no encerramento da sessão, sem presumir
        # soltura física das teclas.
        for input_id, (action, started_at) in list(self.active_inputs.items()):
            self._complete_interval(input_id, action, started_at, now)

        self.active_inputs.clear()
        self.enabled = False
        self.diagonal_active = False
        return self.stats

    def reset(self) -> None:
        self.active_inputs = {}
        self.intervals = []
        self.stats = InputTimingStats()
        self.last_state_update = time.monotonic()
        self.diagonal_active = False

    def snapshot(self) -> InputTimingStats:
        if not self.enabled:
            return self.stats

        now = time.monotonic()
        self._update_continuous_state(now)
        return self.stats

    def active_actions(self) -> set[str]:
        return {action for action, _started_at in self.active_inputs.values()}

    def has_forward(self) -> bool:
        return bool(self.active_actions().intersection(self.FORWARD_ACTIONS))

    def has_lateral(self) -> bool:
        return bool(self.active_actions().intersection(self.LATERAL_ACTIONS))

    def has_action(self, action: str) -> bool:
        return action in self.active_actions()

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

    def on_key_press(self, raw_key: str) -> None:
        if not self.enabled:
            return

        input_id = self.normalize_input_id(raw_key)
        action = self.action_map.get(input_id)
        if not action:
            return

        if input_id in self.active_inputs:
            return

        now = time.monotonic()
        self._update_continuous_state(now)
        self.active_inputs[input_id] = (action, now)
        self.stats.key_presses += 1
        self._register_action_count(action)

    def on_key_release(self, raw_key: str) -> None:
        if not self.enabled:
            return

        input_id = self.normalize_input_id(raw_key)
        if input_id not in self.active_inputs:
            return

        now = time.monotonic()
        self._update_continuous_state(now)
        action, started_at = self.active_inputs.pop(input_id)
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
            self.stats.mouse_presses += 1
            self._register_action_count(action)

            if action == "fire":
                if self.has_forward():
                    self.stats.shots_while_forward += 1
                if self.has_action("crouch"):
                    self.stats.shots_with_crouch += 1
            return

        if input_id not in self.active_inputs:
            return

        stored_action, started_at = self.active_inputs.pop(input_id)
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
        self.stats.scroll_events += 1
        self._register_action_count(action)

        if action in {"jump", "scroll_jump"}:
            self.stats.scroll_jump_events += 1

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
