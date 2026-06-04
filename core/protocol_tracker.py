import time
from dataclasses import dataclass

from core.config import (
    FORWARD_KEYS,
    LATERAL_KEYS,
    MOVEMENT_KEYS,
    AppConfig,
    load_config,
)


@dataclass
class ProtocolStats:
    clean_hits: int = 0
    brake_errors: int = 0
    diagonal_errors: int = 0
    no_ad_errors: int = 0
    ignored_clicks: int = 0
    clicks_while_holding_lateral: int = 0
    valid_stationary_clicks: int = 0
    click_while_moving_errors: int = 0
    diagonal_fire_errors: int = 0
    ws_fire_errors: int = 0

    @property
    def valid_attempts(self) -> int:
        return self.clean_hits + self.brake_errors + self.diagonal_errors + self.no_ad_errors

    @property
    def protocol_rate(self) -> float:
        if self.valid_attempts == 0:
            return 0.0

        return (self.clean_hits / self.valid_attempts) * 100


class ProtocolTracker:
    """
    Classifica tentativas de protocolo no mouse_down real.

    Key down/up mantem apenas o estado atual de movimento. Isso evita que A, W
    ou diagonal sem clique virem erro de disparo.
    """

    WS_RELEASE_ERROR_SECONDS = 0.50

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.enabled = False
        self.pressed_keys: set[str] = set()
        self.last_press_by_key: dict[str, float] = {}
        self.last_release_by_key: dict[str, float] = {}
        self.cooldown_until = 0.0
        self.stats = ProtocolStats()
        self.reset_episode()

    def reset_episode(self) -> None:
        self.episode_active = False
        self.first_movement_key = None
        self.first_lateral_key = None
        self.last_lateral_key = None
        self.last_movement_time = 0.0
        self.brake_done = False
        self.diagonal_error = False

    def clear_input_state(self) -> None:
        self.pressed_keys.clear()
        self.last_press_by_key = {}
        self.last_release_by_key = {}
        self.cooldown_until = 0.0
        self.reset_episode()

    def reset_counters(self) -> None:
        self.stats = ProtocolStats()
        self.clear_input_state()

    def start(self) -> None:
        self.reset_counters()
        self.enabled = True

    def stop(self) -> None:
        self.enabled = False
        self.clear_input_state()

    def is_holding_forward(self) -> bool:
        return bool(self.pressed_keys.intersection(FORWARD_KEYS))

    def is_holding_lateral(self) -> bool:
        return bool(self.pressed_keys.intersection(LATERAL_KEYS))

    def is_holding_diagonal(self) -> bool:
        return self.is_holding_forward() and self.is_holding_lateral()

    def on_key_press(self, key_name: str) -> None:
        if key_name not in MOVEMENT_KEYS:
            return

        if key_name in self.pressed_keys:
            return

        current_time = time.monotonic()
        self.pressed_keys.add(key_name)
        self.last_press_by_key[key_name] = current_time
        self.last_movement_time = current_time

    def on_key_release(self, key_name: str) -> None:
        if key_name in self.pressed_keys:
            self.pressed_keys.remove(key_name)

        if key_name not in MOVEMENT_KEYS:
            return

        current_time = time.monotonic()
        self.last_release_by_key[key_name] = current_time
        self.last_movement_time = current_time

    def had_recent_forward_release(self, current_time: float) -> bool:
        for key_name in FORWARD_KEYS:
            released_at = self.last_release_by_key.get(key_name, 0.0)
            if released_at > 0 and (current_time - released_at) < self.WS_RELEASE_ERROR_SECONDS:
                return True
        return False

    def on_left_click(self) -> None:
        if not self.enabled:
            return

        current_time = time.monotonic()
        if current_time < self.cooldown_until:
            return

        self.cooldown_until = current_time + self.config.post_click_cooldown

        holding_lateral = self.is_holding_lateral()
        holding_forward = self.is_holding_forward()
        holding_diagonal = holding_forward and holding_lateral

        if holding_lateral:
            self.stats.clicks_while_holding_lateral += 1

        if holding_diagonal:
            self.stats.diagonal_errors += 1
            self.stats.diagonal_fire_errors += 1
            self.reset_episode()
            return

        if holding_forward:
            self.stats.brake_errors += 1
            self.stats.ws_fire_errors += 1
            self.reset_episode()
            return

        if self.had_recent_forward_release(current_time):
            self.stats.brake_errors += 1
            self.stats.ws_fire_errors += 1
            self.reset_episode()
            return

        if holding_lateral:
            self.stats.brake_errors += 1
            self.stats.click_while_moving_errors += 1
            self.reset_episode()
            return

        self.stats.clean_hits += 1
        self.stats.valid_stationary_clicks += 1
        self.reset_episode()
