from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from core.config import DATA_DIR
from core.input_timing import InputTimingStats, InputTimingTracker
from core.inventory import (
    equip_owned_weapon,
    get_next_weapon,
    load_inventory,
    register_weapon_purchase,
    register_weapon_usage,
)
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
        self.current_session_mode = "deathmatch"
        self.current_session_start_source = "manual"
        self.session_started_at: datetime | None = None
        self.last_finished_session: DMResult | None = None
        self.current_session_config_snapshot: dict[str, object] = {}
        self.last_session_config_snapshot: dict[str, object] = {}

    @staticmethod
    def format_datetime(value: datetime) -> str:
        return value.strftime(DATETIME_FORMAT)

    def set_session_mode(self, session_mode: str) -> None:
        normalized = str(session_mode or "deathmatch").strip().lower()
        self.current_session_mode = normalized if normalized in {"deathmatch", "ranked"} else "deathmatch"
        self.tracker.set_session_mode(self.current_session_mode)

    def start_session(self, session_mode: str = "deathmatch", start_source: str = "manual") -> dict:
        wallet = load_wallet()
        self.set_session_mode(session_mode)
        self.last_finished_session = None
        self.current_session_start_source = str(start_source or "manual")
        self.current_session_weapon = get_next_weapon()
        self.session_started_at = datetime.now()
        self.current_session_config_snapshot = self.build_session_config_snapshot()
        if self.current_session_mode == "deathmatch":
            register_weapon_usage(self.current_session_weapon)
        self.tracker.start(self.current_session_mode)
        self.input_timing.start()

        return {
            "weapon": self.current_session_weapon,
            "balance": wallet.get("balance", 0),
            "started_at": self.format_datetime(self.session_started_at),
            "session_mode": self.current_session_mode,
        }

    def finish_session(self) -> DMResult:
        wallet = load_wallet()
        stats = self.tracker.stats
        finished_at = datetime.now()
        started_at = self.session_started_at or finished_at

        self.tracker.stop()
        input_stats = self.input_timing.stop()
        protocol_events = self.tracker.export_protocol_events()
        capture_mode = str(getattr(self.input_timing, "capture_mode", "performance") or "performance")
        protocol_summary = {
            "session_mode": self.current_session_mode,
            "start_source": self.current_session_start_source,
            "capture_mode": capture_mode,
            "diagonal_rule_mode": self.tracker.current_diagonal_rule_mode,
            "protocol_events_total": stats.protocol_events_total,
            "protocol_events": protocol_events,
            "clean_hits": stats.clean_hits,
            "brake_errors": stats.brake_errors,
            "diagonal_errors": stats.diagonal_errors,
            "diagonal_faults": stats.diagonal_errors,
            "diagonal_fire_errors": stats.diagonal_fire_errors,
            "jump_strafe_count": stats.jump_strafe_count,
            "jump_window_events": int(input_stats.jump_window_events),
            "ignored_clicks": stats.ignored_clicks,
            "valid_attempts": stats.valid_attempts,
            "protocol_rate": round(stats.protocol_rate, 1),
            "session_config_snapshot": dict(self.current_session_config_snapshot),
        }
        balance_before = int(wallet.get("balance", 0))

        if self.current_session_mode == "ranked":
            economy_settings = dict(self.tracker.config.ranked_economy or {})
            entry_cost = min(max(int(economy_settings.get("entry_cost", 0)), 0), max(balance_before, 0))
            utilization_score = max(0.0, min(float(stats.protocol_rate), 100.0))
            refund = int(round(entry_cost * utilization_score / 100.0))
            bonus = max(int(stats.clean_hits), 0) * max(
                int(economy_settings.get("bonus_per_clean_hit", 0)),
                0,
            )
            earned = refund + bonus - entry_cost
            balance_after_earning = max(balance_before + earned, 0)
            wallet["balance"] = balance_after_earning
            wallet["total_earned"] = int(wallet.get("total_earned", 0)) + refund + bonus
            wallet["total_spent"] = int(wallet.get("total_spent", 0)) + entry_cost
            wallet["session_count"] = int(wallet.get("session_count", 0)) + 1
            session_id = int(wallet.get("session_count", 0))
        else:
            earned = calculate_session_kcreds(stats, self.tracker.config)
            wallet, balance_before, balance_after_earning = apply_session_earning(wallet, earned)
            session_id = wallet["session_count"]

        result = self.build_result(
            session_id=session_id,
            stats=stats,
            earned=earned,
            balance_before=balance_before,
            balance_after_earning=balance_after_earning,
            started_at=started_at,
            finished_at=finished_at,
            input_stats=input_stats,
            protocol_summary=protocol_summary,
        )

        self.last_finished_session = result
        self.last_session_config_snapshot = dict(self.current_session_config_snapshot)
        self.session_started_at = None
        save_wallet(wallet)
        if self.current_session_mode == "ranked":
            wallet = append_session_to_wallet_history(wallet, result)
            save_wallet(wallet)
            append_session_to_csv(result)
            self.last_finished_session = None
        self.save_session_audit_json(
            result,
            protocol_summary=protocol_summary,
            raw_events=list((result.input_payload or {}).get("raw_events", [])),
            useful_inputs=dict((result.input_payload or {}).get("useful_inputs", {})),
            protocol_events=protocol_events,
        )
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
        protocol_summary: dict | None = None,
    ) -> DMResult:
        input_data = input_stats.to_dict() if input_stats is not None else {}
        raw_events = list(input_data.get("raw_events", []))
        protocol_events = list((protocol_summary or {}).get("protocol_events", []))
        useful_inputs = {
            key: value
            for key, value in input_data.items()
            if key not in {"raw_events", "raw_events_total"}
        }
        useful_inputs["session_mode"] = self.current_session_mode
        useful_inputs["capture_mode"] = str(getattr(self.input_timing, "capture_mode", "performance") or "performance")
        useful_inputs["protocol_rule_mode"] = str((protocol_summary or {}).get("diagonal_rule_mode") or "")
        useful_inputs["raw_events_total"] = int(input_data.get("raw_events_total", len(raw_events)))
        useful_inputs["jump_strafe_count"] = int(input_data.get("jump_strafe_count", 0))

        economy_summary = {
            "session_mode": self.current_session_mode,
            "kcreds_earned": int(earned),
            "balance_before": int(balance_before),
            "balance_after_earning": int(balance_after_earning),
            "balance_final": int(balance_after_earning),
            "pending_purchase_enabled": self.current_session_mode == "deathmatch",
        }
        if self.current_session_mode == "ranked":
            settings = dict(self.tracker.config.ranked_economy or {})
            entry_cost = min(max(int(settings.get("entry_cost", 0)), 0), max(int(balance_before), 0))
            utilization_score = max(0.0, min(float(stats.protocol_rate), 100.0))
            refund = int(round(entry_cost * utilization_score / 100.0))
            bonus = max(int(stats.clean_hits), 0) * max(int(settings.get("bonus_per_clean_hit", 0)), 0)
            economy_summary.update({
                "entry_cost": entry_cost,
                "utilization_score": round(utilization_score, 1),
                "refund": refund,
                "bonus": bonus,
                "value_lost": max(entry_cost - refund, 0),
            })
        debug_summary = {
            "start_source": self.current_session_start_source,
            "capture_mode": str(getattr(self.input_timing, "capture_mode", "performance") or "performance"),
            "weapon_used": self.current_session_weapon,
            "raw_events_total": int(input_data.get("raw_events_total", len(raw_events))),
            "protocol_events_total": int((protocol_summary or {}).get("protocol_events_total", 0)),
            "current_diagonal_rule_mode": str((protocol_summary or {}).get("diagonal_rule_mode") or ""),
            "raw_events_compact": str(getattr(self.input_timing, "capture_mode", "performance") or "performance") == "performance",
            "audit_version": "v0.21.12",
        }
        input_payload = {
            "capture_mode": str(getattr(self.input_timing, "capture_mode", "performance") or "performance"),
            "raw_events": raw_events,
            "useful_inputs": useful_inputs,
            "protocol_events": protocol_events,
            "session_config_snapshot": dict(self.current_session_config_snapshot),
            "protocol_summary": {
                key: value
                for key, value in dict(protocol_summary or {}).items()
                if key != "protocol_events"
            },
            "economy_summary": economy_summary,
            "debug_summary": debug_summary,
        }

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
            balance_final=balance_after_earning,
            input_key_presses=int(useful_inputs.get("key_presses", 0)),
            input_mouse_presses=int(useful_inputs.get("mouse_presses", 0)),
            input_scroll_events=int(useful_inputs.get("scroll_events", 0)),
            input_scroll_jump_events=int(useful_inputs.get("scroll_jump_events", 0)),
            input_fire_taps=int(useful_inputs.get("fire_taps", 0)),
            input_fire_bursts=int(useful_inputs.get("fire_bursts", 0)),
            input_fire_long_sprays=int(useful_inputs.get("fire_long_sprays", 0)),
            input_fire_events=int(useful_inputs.get("fire_events", 0)),
            input_average_fire_seconds=float(useful_inputs.get("average_fire_seconds", 0.0)),
            input_max_fire_seconds=float(useful_inputs.get("max_fire_seconds", 0.0)),
            input_shots_while_forward=int(useful_inputs.get("shots_while_forward", 0)),
            input_shots_with_crouch=int(useful_inputs.get("shots_with_crouch", 0)),
            input_crouch_fire_long_count=int(useful_inputs.get("crouch_fire_long_count", 0)),
            input_diagonal_entries=int(useful_inputs.get("diagonal_entries", 0)),
            input_diagonal_seconds=float(useful_inputs.get("diagonal_seconds", 0.0)),
            input_payload=input_payload,
        )

    def save_session_audit_json(
        self,
        result: DMResult,
        protocol_summary: dict[str, object],
        raw_events: list[dict],
        useful_inputs: dict[str, object],
        protocol_events: list[dict],
    ) -> Path:
        audit_dir = DATA_DIR / "input_audit"
        audit_dir.mkdir(parents=True, exist_ok=True)

        safe_mode = result.session_mode or "deathmatch"
        safe_time = result.finished_at.replace(":", "-").replace(" ", "_")
        audit_path = audit_dir / f"session_{result.session_id}_{safe_mode}_{safe_time}.json"
        payload = {
            "session_id": result.session_id,
            "session_mode": result.session_mode,
            "capture_mode": str(getattr(self.input_timing, "capture_mode", "performance") or "performance"),
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "duration_seconds": result.duration_seconds,
            "weapon_used": result.weapon_used,
            "raw_events": raw_events,
            "useful_inputs": useful_inputs,
            "protocol_events": protocol_events,
            "session_config_snapshot": dict(self.current_session_config_snapshot),
            "protocol_summary": {
                key: value
                for key, value in protocol_summary.items()
                if key != "protocol_events"
            },
            "economy_summary": dict((result.input_payload or {}).get("economy_summary", {})),
            "debug_summary": {
                "start_source": self.current_session_start_source,
                "capture_mode": str(getattr(self.input_timing, "capture_mode", "performance") or "performance"),
                "weapon_used": result.weapon_used,
                "raw_events_total": int(useful_inputs.get("raw_events_total", len(raw_events))),
                "protocol_events_total": int((protocol_summary or {}).get("protocol_events_total", len(protocol_events))),
                "current_diagonal_rule_mode": self.tracker.current_diagonal_rule_mode,
                "raw_events_compact": str(getattr(self.input_timing, "capture_mode", "performance") or "performance") == "performance",
                "audit_version": "v0.21.12",
            },
        }

        with audit_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)

        return audit_path

    def build_session_config_snapshot(self) -> dict[str, object]:
        config = self.tracker.config
        input_settings = dict(config.input_timing or {})
        protocol_settings = dict(config.protocol or {})
        automation_settings = dict(config.session_automation or {})
        return {
            "capture_mode": str(getattr(self.input_timing, "capture_mode", "performance") or "performance"),
            "diagonal_rule_mode": self.tracker.current_diagonal_rule_mode,
            "jump_window_ms": int(round(self.input_timing.JUMP_WINDOW_SECONDS * 1000)),
            "jump_pre_grace_ms": int(round(getattr(self.input_timing, "PRE_JUMP_GRACE_SECONDS", 0.15) * 1000)),
            "ws_recent_window_ms": int(round(self.input_timing.RECENT_FORWARD_RELEASE_SECONDS * 1000)),
            "tap_threshold_ms": int(round(float(input_settings.get("tap_max_seconds", 0.12)) * 1000)),
            "burst_threshold_ms": int(round(float(input_settings.get("burst_max_seconds", 0.50)) * 1000)),
            "spray_threshold_ms": int(round(float(input_settings.get("burst_max_seconds", 0.50)) * 1000)),
            "crouch_fire_threshold_ms": int(round(float(input_settings.get("crouch_fire_max_seconds", 0.50)) * 1000)),
            "episode_timeout_ms": int(round(float(config.episode_timeout) * 1000)),
            "post_click_cooldown_ms": int(round(float(config.post_click_cooldown) * 1000)),
            "stationary_click_counts_clean": bool(config.stationary_click_counts_clean),
            "stationary_min_release_ms": int(round(float(config.stationary_min_release_seconds) * 1000)),
            "require_release_at_click": bool(config.require_release_at_click),
            "auto_arm_enabled": bool(automation_settings.get("auto_arm_enabled", False)),
            "capture_enabled": bool(input_settings.get("enabled", True)),
            "ranked_entry_cost": max(int((config.ranked_economy or {}).get("entry_cost", 0)), 0),
            "ranked_bonus_per_clean_hit": max(
                int((config.ranked_economy or {}).get("bonus_per_clean_hit", 0)),
                0,
            ),
            "shot_linked_window_ms": int(round(float(protocol_settings.get("shot_linked_window_seconds", 0.50)) * 1000)),
        }

    def finish_purchase_and_save(self, weapon: dict) -> DMResult | None:
        if self.last_finished_session is None:
            return None
        if self.last_finished_session.session_mode != "deathmatch":
            return None

        wallet = load_wallet()
        owned = weapon["name"] in load_inventory().get("owned_weapons", [])
        if owned:
            equip_owned_weapon(weapon["name"])
        else:
            wallet = buy_weapon_with_kcred(wallet, weapon)
            register_weapon_purchase(weapon, self.last_finished_session.session_id, wallet["balance"])

        self.last_finished_session.weapon_bought_next = weapon["name"]
        self.last_finished_session.weapon_cost = 0 if owned else weapon["cost"]
        self.last_finished_session.balance_final = wallet["balance"]

        wallet = append_session_to_wallet_history(wallet, self.last_finished_session)
        save_wallet(wallet)
        append_session_to_csv(self.last_finished_session)

        finished = self.last_finished_session
        self.last_finished_session = None
        return finished
