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

    @property
    def valid_attempts(self) -> int:
        return self.clean_hits + self.brake_errors + self.diagonal_errors + self.no_ad_errors

    @property
    def protocol_rate(self) -> float:
        if self.valid_attempts == 0:
            return 0.0

        return (self.clean_hits / self.valid_attempts) * 100


class ProtocolTracker:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.enabled = False
        self.pressed_keys: set[str] = set()
        self.cooldown_until = 0.0
        self.stats = ProtocolStats()
        self.diagonal_hold_counted = False
        self.last_movement_release_time = 0.0
        self.reset_episode()

    def reset_episode(self) -> None:
        self.episode_active = False
        self.first_movement_key = None
        self.first_lateral_key = None
        self.last_lateral_key = None
        self.last_movement_time = 0.0
        self.brake_done = False
        self.diagonal_error = False

    def reset_counters(self) -> None:
        self.stats = ProtocolStats()
        self.cooldown_until = 0.0
        self.diagonal_hold_counted = False
        self.last_movement_release_time = 0.0
        self.reset_episode()

    def start(self) -> None:
        self.reset_counters()
        self.enabled = True

    def stop(self) -> None:
        self.enabled = False
        self.diagonal_hold_counted = False
        self.last_movement_release_time = 0.0
        self.reset_episode()

    def is_holding_forward(self) -> bool:
        return bool(self.pressed_keys.intersection(FORWARD_KEYS))

    def is_holding_lateral(self) -> bool:
        return bool(self.pressed_keys.intersection(LATERAL_KEYS))

    def is_holding_diagonal(self) -> bool:
        return self.is_holding_forward() and self.is_holding_lateral()

    def register_diagonal_error_if_needed(self) -> bool:
        """
        Regra v0.9.2:
        andar na diagonal é erro no momento em que acontece, mesmo sem clique.

        Para não explodir o contador enquanto as teclas continuam seguradas,
        o mesmo hold diagonal conta uma vez. Ao soltar e formar nova diagonal,
        conta novamente.
        """
        if not self.enabled:
            return False

        if not self.is_holding_diagonal():
            return False

        if self.diagonal_hold_counted:
            return False

        self.stats.diagonal_errors += 1
        self.diagonal_hold_counted = True
        self.reset_episode()
        return True

    def start_episode_with_key(self, key_name: str, current_time: float, pressed_before: set[str]) -> None:
        self.episode_active = True
        self.first_movement_key = key_name
        self.last_movement_time = current_time
        self.brake_done = False
        self.diagonal_error = False

        if key_name in LATERAL_KEYS:
            self.first_lateral_key = key_name
            self.last_lateral_key = key_name

            if pressed_before.intersection(FORWARD_KEYS):
                self.diagonal_error = True
        else:
            self.first_lateral_key = None
            self.last_lateral_key = None

    def on_key_press(self, key_name: str) -> None:
        if key_name not in MOVEMENT_KEYS:
            return

        if key_name in self.pressed_keys:
            return

        current_time = time.monotonic()
        pressed_before = set(self.pressed_keys)
        self.pressed_keys.add(key_name)

        if not self.enabled:
            return

        # Regra rígida: qualquer combinação W/S + A/D é erro imediato,
        # mesmo que o jogador não atire.
        if self.register_diagonal_error_if_needed():
            return

        episode_timed_out = (
            not self.episode_active
            or ((current_time - self.last_movement_time) > self.config.episode_timeout)
        )

        if episode_timed_out:
            self.start_episode_with_key(key_name, current_time, pressed_before)
            return

        if (
            key_name in LATERAL_KEYS
            and self.first_lateral_key is None
            and not pressed_before.intersection(FORWARD_KEYS)
        ):
            self.start_episode_with_key(key_name, current_time, pressed_before)
            return

        self.last_movement_time = current_time

        if key_name in FORWARD_KEYS:
            if self.first_lateral_key is not None:
                self.diagonal_error = True
            return

        if key_name in LATERAL_KEYS:
            if pressed_before.intersection(FORWARD_KEYS):
                self.diagonal_error = True

            if self.first_lateral_key is None:
                self.first_lateral_key = key_name
                self.last_lateral_key = key_name
                return

            if key_name != self.first_lateral_key:
                self.brake_done = True

            self.last_lateral_key = key_name

    def on_key_release(self, key_name: str) -> None:
        if key_name in self.pressed_keys:
            self.pressed_keys.remove(key_name)

        if key_name in MOVEMENT_KEYS:
            self.last_movement_release_time = time.monotonic()

        # Libera a contagem para uma nova diagonal somente quando o jogador
        # realmente saiu da combinação W/S + A/D.
        if not self.is_holding_diagonal():
            self.diagonal_hold_counted = False

    def can_count_stationary_click_as_clean(self, current_time: float) -> bool:
        if not self.config.stationary_click_counts_clean:
            return False

        if self.is_holding_forward() or self.is_holding_lateral():
            return False

        if self.last_movement_release_time <= 0:
            return True

        return (current_time - self.last_movement_release_time) >= self.config.stationary_min_release_seconds

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

        # Regra v0.20.3:
        # se nenhuma tecla de movimento está ativa e o jogador já passou pelo
        # tempo mínimo de estabilização, o disparo conta como acerto limpo.
        # Isso representa o caso correto: jogador parado, tiro permitido.
        if self.can_count_stationary_click_as_clean(current_time):
            self.stats.clean_hits += 1
            self.reset_episode()
            return

        # Regra rígida: enquanto W/S estiver segurado, clicar é proibido.
        # W/S + A/D + clique = erro diagonal.
        # W/S + clique sem A/D = erro sem A/D.
        if holding_forward:
            if holding_diagonal:
                self.stats.diagonal_errors += 1
                self.diagonal_hold_counted = True
            else:
                self.stats.no_ad_errors += 1

            self.reset_episode()
            return

        if (not self.episode_active) or ((current_time - self.last_movement_time) > self.config.episode_timeout):
            self.stats.ignored_clicks += 1
            self.reset_episode()
            return

        if self.first_lateral_key is None:
            self.stats.no_ad_errors += 1
            self.reset_episode()
            return

        if self.diagonal_error:
            self.stats.diagonal_errors += 1
            self.reset_episode()
            return

        is_clean = self.brake_done

        if self.config.require_release_at_click and holding_lateral:
            is_clean = False

        if is_clean:
            self.stats.clean_hits += 1
        else:
            self.stats.brake_errors += 1

        self.reset_episode()
