from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from core.config import AppConfig, load_config
from core.input_timing import FireEvaluationContext

RULE_STATIONARY_SHOT = "Stationary Shot Rule"
RULE_COUNTER_STRAFE = "Counter-Strafe Rule"
RULE_WS_FIRE = "W/S Fire Rule"
RULE_DIAGONAL_FOOTWORK = "Diagonal Footwork Rule"
RULE_JUMP_WINDOW = "Jump Window Rule"
RULE_RANKED_AUDIT = "Ranked Audit Rule"

DIAGONAL_RULE_LABELS = {
    "strict_footwork": "Strict Footwork",
    "shot_linked": "Shot-Linked",
    "informational": "Informational",
    "disabled": "Disabled",
}

STANDARD_RULE_MODE = "standard"
AUDIT_ONLY_RULE_MODE = "audit_only"


@dataclass
class ProtocolEvent:
    event_index: int
    event_type: str
    rule_name: str
    rule_mode: str
    severity: str
    penalized: bool
    coins_delta: int | None
    reason: str
    triggered_by: str
    windows_timestamp: str
    monotonic_timestamp: float
    input_snapshot: dict[str, bool]
    context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["monotonic_timestamp"] = round(self.monotonic_timestamp, 6)
        return data


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
    protocol_events_total: int = 0
    protocol_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def valid_attempts(self) -> int:
        return self.clean_hits + self.brake_errors + self.diagonal_errors

    @property
    def protocol_rate(self) -> float:
        if self.valid_attempts == 0:
            return 0.0
        return (self.clean_hits / self.valid_attempts) * 100


class ProtocolTracker:
    """
    Classifica eventos interpretados de protocolo usando o snapshot autoritativo
    vindo do InputTimingTracker.

    - click valido/erro continua nascendo apenas em mouse_down;
    - excecao: strict_footwork pode gerar falta de diagonal na entrada do estado.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.enabled = False
        self.cooldown_until = 0.0
        self.stats = ProtocolStats()
        self.current_session_mode = "deathmatch"
        self.current_diagonal_rule_mode = self._resolve_diagonal_rule_mode(self.current_session_mode)
        self.last_diagonal_exit_at = 0.0
        self.diagonal_state_active = False
        self.strict_diagonal_fault_active = False

    @property
    def shot_linked_window_seconds(self) -> float:
        protocol_settings = dict(self.config.protocol or {})
        return max(float(protocol_settings.get("shot_linked_window_seconds", 0.50)), 0.05)

    def recent_protocol_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        protocol_settings = dict(self.config.protocol or {})
        event_limit = limit or int(protocol_settings.get("debug_event_limit", 12))
        event_limit = max(int(event_limit), 1)
        return self.stats.protocol_events[-event_limit:]

    def set_session_mode(self, session_mode: str) -> None:
        normalized = str(session_mode or "deathmatch").strip().lower()
        self.current_session_mode = normalized if normalized in {"deathmatch", "ranked"} else "deathmatch"
        self.current_diagonal_rule_mode = self._resolve_diagonal_rule_mode(self.current_session_mode)

    def reset_counters(self) -> None:
        self.stats = ProtocolStats()
        self.cooldown_until = 0.0
        self.last_diagonal_exit_at = 0.0
        self.diagonal_state_active = False
        self.strict_diagonal_fault_active = False

    def start(self, session_mode: str | None = None) -> None:
        if session_mode is not None:
            self.set_session_mode(session_mode)
        self.reset_counters()
        self.enabled = True

        if self.current_session_mode == "ranked":
            self._record_protocol_event(
                event_type="ranked_audit_active",
                rule_name=RULE_RANKED_AUDIT,
                rule_mode=AUDIT_ONLY_RULE_MODE,
                severity="info",
                penalized=False,
                coins_delta=0,
                reason="Ranked sessions record protocol audit events but never change Coins.",
                triggered_by="session_start",
                monotonic_timestamp=time.monotonic(),
                input_snapshot={},
                context={},
            )

    def stop(self) -> None:
        self.enabled = False
        self.cooldown_until = 0.0
        self.diagonal_state_active = False
        self.strict_diagonal_fault_active = False

    def on_input_state_changed(self, context: FireEvaluationContext) -> None:
        if not self.enabled:
            return

        current_time = time.monotonic()
        diagonal_active = bool(context.has_diagonal_active)

        if diagonal_active and not self.diagonal_state_active:
            self._handle_diagonal_entry(context, current_time)

        if not diagonal_active and self.diagonal_state_active:
            self.last_diagonal_exit_at = current_time
            self.strict_diagonal_fault_active = False

        self.diagonal_state_active = diagonal_active

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
            self._record_protocol_event(
                event_type="jump_window_ignored_click",
                rule_name=RULE_JUMP_WINDOW,
                rule_mode=STANDARD_RULE_MODE,
                severity="info",
                penalized=False,
                coins_delta=0,
                reason="Movement inside the jump window is audit-only and does not count as a normal movement penalty.",
                triggered_by="mouse_down",
                monotonic_timestamp=current_time,
                input_snapshot=context.active_state_snapshot,
                context=context.to_dict(),
            )
            return

        diagonal_state = self._classify_diagonal_click_state(context, current_time)
        if diagonal_state == "strict_active":
            self._record_protocol_event(
                event_type="strict_diagonal_click_observed",
                rule_name=RULE_DIAGONAL_FOOTWORK,
                rule_mode=self.current_diagonal_rule_mode,
                severity="info",
                penalized=False,
                coins_delta=0,
                reason="Shot happened during a diagonal state that was already penalized by Strict Footwork.",
                triggered_by="mouse_down",
                monotonic_timestamp=current_time,
                input_snapshot=context.active_state_snapshot,
                context=context.to_dict(),
            )
            return

        if diagonal_state == "shot_linked_fault":
            self.stats.diagonal_errors += 1
            self.stats.diagonal_fire_errors += 1
            self._record_protocol_event(
                event_type="diagonal_fire_fault",
                rule_name=RULE_DIAGONAL_FOOTWORK,
                rule_mode=self.current_diagonal_rule_mode,
                severity="error",
                penalized=self._coins_enabled(),
                coins_delta=self._coins_delta_for_diagonal_penalty(),
                reason="Shot happened during diagonal movement or within the shot-linked diagonal grace window.",
                triggered_by="mouse_down",
                monotonic_timestamp=current_time,
                input_snapshot=context.active_state_snapshot,
                context=context.to_dict(),
            )
            return

        if diagonal_state == "informational":
            self._record_protocol_event(
                event_type="diagonal_fire_observed",
                rule_name=RULE_DIAGONAL_FOOTWORK,
                rule_mode=self.current_diagonal_rule_mode,
                severity="info",
                penalized=False,
                coins_delta=0,
                reason="Diagonal movement was recorded for audit only and does not score as a diagonal penalty in this mode.",
                triggered_by="mouse_down",
                monotonic_timestamp=current_time,
                input_snapshot=context.active_state_snapshot,
                context=context.to_dict(),
            )

        if context.has_forward_active or context.forward_released_recently:
            self.stats.brake_errors += 1
            self.stats.ws_fire_errors += 1
            self._record_protocol_event(
                event_type="ws_fire_error",
                rule_name=RULE_WS_FIRE,
                rule_mode=STANDARD_RULE_MODE,
                severity="severe",
                penalized=self._coins_enabled(),
                coins_delta=self._coins_delta_for_brake_penalty(),
                reason="W or S was active, or was released too recently, at the time of the shot.",
                triggered_by="mouse_down",
                monotonic_timestamp=current_time,
                input_snapshot=context.active_state_snapshot,
                context=context.to_dict(),
            )
            return

        if context.has_lateral_active:
            self.stats.brake_errors += 1
            self.stats.click_while_moving_errors += 1
            self._record_protocol_event(
                event_type="counter_strafe_error",
                rule_name=RULE_COUNTER_STRAFE,
                rule_mode=STANDARD_RULE_MODE,
                severity="error",
                penalized=self._coins_enabled(),
                coins_delta=self._coins_delta_for_brake_penalty(),
                reason="A or D was still active at click time, so the shot missed the counter-strafe window.",
                triggered_by="mouse_down",
                monotonic_timestamp=current_time,
                input_snapshot=context.active_state_snapshot,
                context=context.to_dict(),
            )
            return

        self.stats.clean_hits += 1
        self.stats.valid_stationary_clicks += 1
        self._record_protocol_event(
            event_type="stationary_clean",
            rule_name=RULE_STATIONARY_SHOT,
            rule_mode=STANDARD_RULE_MODE,
            severity="success",
            penalized=False,
            coins_delta=self._coins_delta_for_clean_hit(),
            reason="No movement was active at click time, so the shot counts as stationary and clean.",
            triggered_by="mouse_down",
            monotonic_timestamp=current_time,
            input_snapshot=context.active_state_snapshot,
            context=context.to_dict(),
        )

    def _handle_diagonal_entry(self, context: FireEvaluationContext, current_time: float) -> None:
        if context.within_jump_window:
            return

        if self.current_diagonal_rule_mode == "disabled":
            return

        if self.current_diagonal_rule_mode == "strict_footwork":
            self.stats.diagonal_errors += 1
            self.strict_diagonal_fault_active = True
            self._record_protocol_event(
                event_type="diagonal_movement_fault",
                rule_name=RULE_DIAGONAL_FOOTWORK,
                rule_mode=self.current_diagonal_rule_mode,
                severity="error",
                penalized=self._coins_enabled(),
                coins_delta=self._coins_delta_for_diagonal_penalty(),
                reason="Diagonal movement entered a strict footwork state and counts as a protocol fault even without a shot.",
                triggered_by="movement",
                monotonic_timestamp=current_time,
                input_snapshot=context.active_state_snapshot,
                context=context.to_dict(),
            )
            return

        severity = "info"
        reason = "Diagonal movement was recorded for protocol review without changing Coins."
        if self.current_diagonal_rule_mode == "shot_linked":
            reason = "Diagonal movement opened a shot-linked review window. It only penalizes if a shot follows in time."

        self._record_protocol_event(
            event_type="diagonal_movement_observed",
            rule_name=RULE_DIAGONAL_FOOTWORK,
            rule_mode=self.current_diagonal_rule_mode,
            severity=severity,
            penalized=False,
            coins_delta=0,
            reason=reason,
            triggered_by="movement",
            monotonic_timestamp=current_time,
            input_snapshot=context.active_state_snapshot,
            context=context.to_dict(),
        )

    def _classify_diagonal_click_state(self, context: FireEvaluationContext, current_time: float) -> str:
        diagonal_recent = (
            self.last_diagonal_exit_at > 0
            and (current_time - self.last_diagonal_exit_at) <= self.shot_linked_window_seconds
        )

        if self.current_diagonal_rule_mode == "strict_footwork":
            if context.has_diagonal_active or self.strict_diagonal_fault_active:
                return "strict_active"
            return "none"

        if self.current_diagonal_rule_mode == "shot_linked":
            if context.has_diagonal_active or diagonal_recent:
                return "shot_linked_fault"
            return "none"

        if self.current_diagonal_rule_mode == "informational":
            if context.has_diagonal_active or diagonal_recent:
                return "informational"
            return "none"

        return "none"

    def _resolve_diagonal_rule_mode(self, session_mode: str) -> str:
        protocol_settings = dict(self.config.protocol or {})
        if str(session_mode).strip().lower() == "ranked":
            return str(protocol_settings.get("diagonal_footwork_rule_ranked") or "informational")
        return str(protocol_settings.get("diagonal_footwork_rule_deathmatch") or "strict_footwork")

    def _coins_enabled(self) -> bool:
        return self.current_session_mode == "deathmatch"

    def _coins_delta_for_clean_hit(self) -> int:
        if not self._coins_enabled():
            return 0
        return max(int(self.config.kcred_per_clean_hit), 0)

    def _coins_delta_for_brake_penalty(self) -> int:
        if not self._coins_enabled():
            return 0
        return -max(int(self.config.kcred_penalty_brake_error), 0)

    def _coins_delta_for_diagonal_penalty(self) -> int:
        if not self._coins_enabled():
            return 0
        return -max(int(self.config.kcred_penalty_diagonal_error), 0)

    def _record_protocol_event(
        self,
        event_type: str,
        rule_name: str,
        rule_mode: str,
        severity: str,
        penalized: bool,
        coins_delta: int | None,
        reason: str,
        triggered_by: str,
        monotonic_timestamp: float,
        input_snapshot: dict[str, bool],
        context: dict[str, Any],
    ) -> None:
        event = ProtocolEvent(
            event_index=self.stats.protocol_events_total + 1,
            event_type=event_type,
            rule_name=rule_name,
            rule_mode=rule_mode,
            severity=severity,
            penalized=bool(penalized),
            coins_delta=coins_delta,
            reason=reason,
            triggered_by=triggered_by,
            windows_timestamp=datetime.now().isoformat(timespec="milliseconds"),
            monotonic_timestamp=monotonic_timestamp,
            input_snapshot=dict(input_snapshot or {}),
            context=context,
        )
        self.stats.protocol_events_total += 1
        self.stats.protocol_events.append(event.to_dict())
