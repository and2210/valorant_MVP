from __future__ import annotations

import time
from dataclasses import dataclass

from core.config import AppConfig, load_config
from core.input_timing import FireEvaluationContext


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
    Classifica apenas tentativas reais de disparo.

    O estado de tecla vive no InputTimingTracker. Aqui a gente so recebe o
    snapshot do mouse_down e decide se foi valido, freio, diagonal ou W/S.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.enabled = False
        self.cooldown_until = 0.0
        self.stats = ProtocolStats()

    def reset_counters(self) -> None:
        self.stats = ProtocolStats()
        self.cooldown_until = 0.0

    def start(self) -> None:
        self.reset_counters()
        self.enabled = True

    def stop(self) -> None:
        self.enabled = False
        self.cooldown_until = 0.0

    def on_left_click(self, context: FireEvaluationContext) -> None:
        if not self.enabled:
            return

        current_time = time.monotonic()
        if current_time < self.cooldown_until:
            return

        self.cooldown_until = current_time + self.config.post_click_cooldown

        if context.has_lateral_active:
            self.stats.clicks_while_holding_lateral += 1

        if context.within_jump_window and context.has_any_movement_active:
            self.stats.ignored_clicks += 1
            return

        if context.has_diagonal_active:
            self.stats.diagonal_errors += 1
            self.stats.diagonal_fire_errors += 1
            return

        if context.has_forward_active or context.forward_released_recently:
            self.stats.brake_errors += 1
            self.stats.ws_fire_errors += 1
            return

        if context.has_lateral_active:
            self.stats.brake_errors += 1
            self.stats.click_while_moving_errors += 1
            return

        self.stats.clean_hits += 1
        self.stats.valid_stationary_clicks += 1
