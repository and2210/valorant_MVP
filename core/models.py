from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class DMResult:
    session_id: int
    started_at: str
    finished_at: str
    duration_seconds: int
    weapon_used: str
    clean_hits: int
    brake_errors: int
    diagonal_errors: int
    no_ad_errors: int
    valid_attempts: int
    ignored_clicks: int
    clicks_while_holding_lateral: int
    protocol_rate: float
    kcreds_earned: int
    balance_before: int
    balance_after_earning: int
    session_mode: str = "deathmatch"
    weapon_bought_next: str = ""
    weapon_cost: int = 0
    balance_final: int = 0
    input_key_presses: int = 0
    input_mouse_presses: int = 0
    input_scroll_events: int = 0
    input_scroll_jump_events: int = 0
    input_fire_taps: int = 0
    input_fire_bursts: int = 0
    input_fire_long_sprays: int = 0
    input_fire_events: int = 0
    input_average_fire_seconds: float = 0.0
    input_max_fire_seconds: float = 0.0
    input_shots_while_forward: int = 0
    input_shots_with_crouch: int = 0
    input_crouch_fire_long_count: int = 0
    input_diagonal_entries: int = 0
    input_diagonal_seconds: float = 0.0
    input_payload: dict[str, Any] | None = None

    @property
    def datetime(self) -> str:
        return self.finished_at

    @property
    def total_errors(self) -> int:
        return self.brake_errors + self.diagonal_errors + self.no_ad_errors

    @property
    def has_attempts(self) -> bool:
        return self.valid_attempts > 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["datetime"] = self.datetime
        return data

    def to_wallet_history_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "time": self.datetime,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "weapon_used": self.weapon_used,
            "clean_hits": self.clean_hits,
            "brake_errors": self.brake_errors,
            "diagonal_errors": self.diagonal_errors,
            "no_ad_errors": self.no_ad_errors,
            "valid_attempts": self.valid_attempts,
            "ignored_clicks": self.ignored_clicks,
            "clicks_while_holding_lateral": self.clicks_while_holding_lateral,
            "protocol_rate": self.protocol_rate,
            "earned": self.kcreds_earned,
            "kcreds_earned": self.kcreds_earned,
            "balance_before": self.balance_before,
            "balance_after_earning": self.balance_after_earning,
            "weapon_bought_next": self.weapon_bought_next,
            "weapon_cost": self.weapon_cost,
            "balance_final": self.balance_final,
            "input_key_presses": self.input_key_presses,
            "input_mouse_presses": self.input_mouse_presses,
            "input_scroll_events": self.input_scroll_events,
            "input_scroll_jump_events": self.input_scroll_jump_events,
            "input_fire_taps": self.input_fire_taps,
            "input_fire_bursts": self.input_fire_bursts,
            "input_fire_long_sprays": self.input_fire_long_sprays,
            "input_fire_events": self.input_fire_events,
            "input_average_fire_seconds": self.input_average_fire_seconds,
            "input_max_fire_seconds": self.input_max_fire_seconds,
            "input_shots_while_forward": self.input_shots_while_forward,
            "input_shots_with_crouch": self.input_shots_with_crouch,
            "input_crouch_fire_long_count": self.input_crouch_fire_long_count,
            "input_diagonal_entries": self.input_diagonal_entries,
            "input_diagonal_seconds": self.input_diagonal_seconds,
            "input_payload": self.input_payload or {},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DMResult":
        finished_at = data.get("finished_at") or data.get("datetime") or data.get("time") or ""
        started_at = data.get("started_at") or finished_at

        return cls(
            session_id=to_int(data.get("session_id")),
            started_at=str(started_at),
            finished_at=str(finished_at),
            duration_seconds=to_int(data.get("duration_seconds")),
            weapon_used=str(data.get("weapon_used") or "Classic"),
            clean_hits=to_int(data.get("clean_hits")),
            brake_errors=to_int(data.get("brake_errors")),
            diagonal_errors=to_int(data.get("diagonal_errors")),
            no_ad_errors=to_int(data.get("no_ad_errors")),
            valid_attempts=to_int(data.get("valid_attempts")),
            ignored_clicks=to_int(data.get("ignored_clicks")),
            clicks_while_holding_lateral=to_int(data.get("clicks_while_holding_lateral")),
            protocol_rate=to_float(data.get("protocol_rate")),
            kcreds_earned=to_int(data.get("kcreds_earned", data.get("earned"))),
            balance_before=to_int(data.get("balance_before")),
            balance_after_earning=to_int(data.get("balance_after_earning")),
            session_mode=str(data.get("session_mode") or "deathmatch"),
            weapon_bought_next=str(data.get("weapon_bought_next") or ""),
            weapon_cost=to_int(data.get("weapon_cost")),
            balance_final=to_int(data.get("balance_final", data.get("balance_after_earning"))),
            input_key_presses=to_int(data.get("input_key_presses")),
            input_mouse_presses=to_int(data.get("input_mouse_presses")),
            input_scroll_events=to_int(data.get("input_scroll_events")),
            input_scroll_jump_events=to_int(data.get("input_scroll_jump_events")),
            input_fire_taps=to_int(data.get("input_fire_taps")),
            input_fire_bursts=to_int(data.get("input_fire_bursts")),
            input_fire_long_sprays=to_int(data.get("input_fire_long_sprays")),
            input_fire_events=to_int(data.get("input_fire_events")),
            input_average_fire_seconds=to_float(data.get("input_average_fire_seconds")),
            input_max_fire_seconds=to_float(data.get("input_max_fire_seconds")),
            input_shots_while_forward=to_int(data.get("input_shots_while_forward")),
            input_shots_with_crouch=to_int(data.get("input_shots_with_crouch")),
            input_crouch_fire_long_count=to_int(data.get("input_crouch_fire_long_count")),
            input_diagonal_entries=to_int(data.get("input_diagonal_entries")),
            input_diagonal_seconds=to_float(data.get("input_diagonal_seconds")),
            input_payload=data.get("input_payload") if isinstance(data.get("input_payload"), dict) else {},
        )


def now_text() -> str:
    return datetime.now().strftime(DATETIME_FORMAT)


def seconds_between(started_at: datetime, finished_at: datetime) -> int:
    return max(int((finished_at - started_at).total_seconds()), 0)
