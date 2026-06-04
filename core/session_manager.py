from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from core.config import DATA_DIR
from core.input_timing import InputTimingStats, InputTimingTracker
from core.inventory import get_next_weapon, register_weapon_purchase, register_weapon_usage
from core.kcred_engine import apply_session_earning
from core.kcred_engine import buy_weapon as buy_weapon_with_kcred
from core.kcred_engine import calculate_session_kcreds
from core.models import DATETIME_FORMAT, DMResult, seconds_between
from core.persistence import (
    append_session_to_csv,
    append_session_to_wallet_history,
    load_wallet,
    save_wallet,
)
from core.protocol_tracker import ProtocolStats, ProtocolTracker


class SessionManager:
    def __init__(self, tracker: ProtocolTracker, input_timing: InputTimingTracker | None = None) -> None:
        self.tracker = tracker
        self.input_timing = input_timing or InputTimingTracker(tracker.config)
        self.current_session_weapon = "Classic"
        self.current_session_mode = "dm_training"
        self.current_training_method = ""
        self.session_started_at: datetime | None = None
        self.last_finished_session: DMResult | None = None

    @staticmethod
    def format_datetime(value: datetime) -> str:
        return value.strftime(DATETIME_FORMAT)

    @staticmethod
    def normalize_session_mode(session_mode: str) -> str:
        value = str(session_mode or "dm_training").strip().lower()
        if value in {"ranked", "competitive"}:
            return "ranked"
        return "dm_training"

    def start_session(self, session_mode: str = "dm_training", training_method: str = "") -> dict:
        wallet = load_wallet()
        self.current_session_mode = self.normalize_session_mode(session_mode)
        self.current_training_method = str(training_method or "")
        self.session_started_at = datetime.now()

        if self.current_session_mode == "dm_training":
            self.current_session_weapon = get_next_weapon()
            register_weapon_usage(self.current_session_weapon)
        else:
            self.current_session_weapon = "Ranked"

        self.tracker.start()
        self.input_timing.start(
            session_ref=self.format_datetime(self.session_started_at),
            session_mode=self.current_session_mode,
            training_method=self.current_training_method,
        )

        return {
            "weapon": self.current_session_weapon,
            "balance": wallet.get("balance", 0),
            "started_at": self.format_datetime(self.session_started_at),
            "session_mode": self.current_session_mode,
            "training_method": self.current_training_method,
        }

    def finish_session(self) -> DMResult:
        wallet = load_wallet()
        stats = self.tracker.stats
        is_dm_training = self.current_session_mode == "dm_training"
        earned = calculate_session_kcreds(stats, self.tracker.config) if is_dm_training else 0
        finished_at = datetime.now()
        started_at = self.session_started_at or finished_at

        self.tracker.stop()
        input_stats = self.input_timing.stop()

        if is_dm_training:
            wallet, balance_before, balance_after_earning = apply_session_earning(wallet, earned)
            session_id = wallet["session_count"]
        else:
            balance_before = int(wallet.get("balance", 0))
            balance_after_earning = balance_before
            session_id = 0

        result = self.build_result(
            session_id=session_id,
            stats=stats,
            earned=earned,
            balance_before=balance_before,
            balance_after_earning=balance_after_earning,
            started_at=started_at,
            finished_at=finished_at,
            input_stats=input_stats,
        )

        self.save_input_audit(result, input_stats)

        if is_dm_training:
            save_wallet(wallet)
            self.last_finished_session = result
        else:
            self.last_finished_session = None

        self.session_started_at = None
        return result

    def build_result(
        self,
        session_id: int,
        stats: ProtocolStats,
        earned: int,
        balance_before: int,
        balance_after_earning: int,
        started_at: datetime,
        finished_at: datetime,
        input_stats: InputTimingStats | None = None,
    ) -> DMResult:
        input_payload = input_stats.to_dict() if input_stats is not None else {}

        return DMResult(
            session_id=session_id,
            started_at=self.format_datetime(started_at),
            finished_at=self.format_datetime(finished_at),
            duration_seconds=seconds_between(started_at, finished_at),
            weapon_used=self.current_session_weapon,
            clean_hits=stats.clean_hits,
            brake_errors=stats.brake_errors,
            diagonal_errors=stats.diagonal_errors,
            no_ad_errors=stats.no_ad_errors,
            valid_attempts=stats.valid_attempts,
            ignored_clicks=stats.ignored_clicks,
            clicks_while_holding_lateral=stats.clicks_while_holding_lateral,
            protocol_rate=round(stats.protocol_rate, 1),
            kcreds_earned=earned,
            balance_before=balance_before,
            balance_after_earning=balance_after_earning,
            session_mode=self.current_session_mode,
            training_method=self.current_training_method,
            balance_final=balance_after_earning,
            input_key_presses=int(input_payload.get("key_presses", 0)),
            input_mouse_presses=int(input_payload.get("mouse_presses", 0)),
            input_scroll_events=int(input_payload.get("scroll_events", 0)),
            input_scroll_jump_events=int(input_payload.get("scroll_jump_events", 0)),
            input_fire_taps=int(input_payload.get("fire_taps", 0)),
            input_fire_bursts=int(input_payload.get("fire_bursts", 0)),
            input_fire_long_sprays=int(input_payload.get("fire_long_sprays", 0)),
            input_fire_events=int(input_payload.get("fire_events", 0)),
            input_average_fire_seconds=float(input_payload.get("average_fire_seconds", 0.0)),
            input_max_fire_seconds=float(input_payload.get("max_fire_seconds", 0.0)),
            input_shots_while_forward=int(input_payload.get("shots_while_forward", 0)),
            input_shots_with_crouch=int(input_payload.get("shots_with_crouch", 0)),
            input_crouch_fire_long_count=int(input_payload.get("crouch_fire_long_count", 0)),
            input_diagonal_entries=int(input_payload.get("diagonal_entries", 0)),
            input_diagonal_seconds=float(input_payload.get("diagonal_seconds", 0.0)),
            input_payload=input_payload,
        )

    def save_input_audit(self, result: DMResult, input_stats: InputTimingStats) -> Path:
        audit_dir = DATA_DIR / "input_audit"
        audit_dir.mkdir(parents=True, exist_ok=True)

        started_safe = result.started_at.replace(":", "").replace(" ", "_").replace("-", "")
        session_ref = f"session_{result.session_id:04d}" if result.session_id > 0 else f"{result.session_mode}_{started_safe}"
        path = audit_dir / f"{session_ref}.json"
        payload = {
            "session": {
                "session_id": result.session_id,
                "session_ref": session_ref,
                "session_mode": result.session_mode,
                "training_method": result.training_method,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "duration_seconds": result.duration_seconds,
                "weapon_used": result.weapon_used,
                "kcreds_earned": result.kcreds_earned,
            },
            "summary": input_stats.to_dict(),
            "protocol_summary": asdict(self.tracker.stats),
            "raw_events": self.input_timing.raw_events_to_dicts(),
        }

        with path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)

        return path

    def finish_purchase_and_save(self, weapon: dict) -> DMResult | None:
        if self.last_finished_session is None:
            return None

        wallet = load_wallet()
        wallet = buy_weapon_with_kcred(wallet, weapon)
        register_weapon_purchase(weapon, self.last_finished_session.session_id, wallet["balance"])

        self.last_finished_session.weapon_bought_next = weapon["name"]
        self.last_finished_session.weapon_cost = weapon["cost"]
        self.last_finished_session.balance_final = wallet["balance"]

        wallet = append_session_to_wallet_history(wallet, self.last_finished_session)
        save_wallet(wallet)
        append_session_to_csv(self.last_finished_session)

        finished = self.last_finished_session
        self.last_finished_session = None
        return finished
