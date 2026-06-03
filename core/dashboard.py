from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from core.history import HistorySummary, build_history_summary
from core.inventory import build_inventory_summary, get_next_weapon
from core.models import DMResult
from core.config import XP_PER_LEVEL, load_config
from core.persistence import load_all_sessions, load_wallet
from core.tracker_importer import TrackerStats, build_tracker_stats


@dataclass
class PlayerProgress:
    level: int = 1
    total_xp: int = 0
    current_level_xp: int = 0
    next_level_xp: int = XP_PER_LEVEL
    progress_rate: float = 0.0


@dataclass
class TodayStats:
    sessions: int = 0
    clean_hits: int = 0
    valid_attempts: int = 0
    kcreds_earned: int = 0
    average_protocol_rate: float = 0.0


@dataclass
class DashboardStats:
    balance: int = 0
    next_weapon: str = "Classic"
    total_sessions: int = 0
    total_clean_hits: int = 0
    total_valid_attempts: int = 0
    average_protocol_rate: float = 0.0
    best_weapon: str = ""
    best_weapon_rate: float = 0.0
    best_session_id: int = 0
    best_session_rate: float = 0.0
    last_session: DMResult | None = None
    today: TodayStats = field(default_factory=TodayStats)
    progress: PlayerProgress = field(default_factory=PlayerProgress)
    inventory_weapon_count: int = 0
    owned_weapon_count: int = 0
    tracker: TrackerStats = field(default_factory=TrackerStats)


def build_player_progress(total_clean_hits: int) -> PlayerProgress:
    config = load_config()
    xp_per_clean_hit = max(int(config.xp_per_clean_hit), 0)
    xp_per_level = max(int(config.xp_per_level), 1)

    total_xp = max(int(total_clean_hits), 0) * xp_per_clean_hit
    completed_levels = total_xp // xp_per_level
    current_level_xp = total_xp % xp_per_level
    progress_rate = round((current_level_xp / xp_per_level) * 100, 1)

    return PlayerProgress(
        level=completed_levels + 1,
        total_xp=total_xp,
        current_level_xp=current_level_xp,
        next_level_xp=xp_per_level,
        progress_rate=progress_rate,
    )


def build_today_stats(sessions: list[DMResult]) -> TodayStats:
    today_text = date.today().isoformat()
    today_sessions = [session for session in sessions if str(session.finished_at).startswith(today_text)]

    stats = TodayStats(sessions=len(today_sessions))

    if not today_sessions:
        return stats

    protocol_sum = 0.0
    protocol_count = 0

    for session in today_sessions:
        stats.clean_hits += session.clean_hits
        stats.valid_attempts += session.valid_attempts
        stats.kcreds_earned += session.kcreds_earned

        if session.has_attempts:
            protocol_sum += session.protocol_rate
            protocol_count += 1

    if protocol_count > 0:
        stats.average_protocol_rate = round(protocol_sum / protocol_count, 1)

    return stats


def get_best_weapon(summary: HistorySummary) -> tuple[str, float]:
    if not summary.average_protocol_by_weapon:
        return "", 0.0

    weapon, rate = max(
        summary.average_protocol_by_weapon.items(),
        key=lambda item: item[1],
    )
    return weapon, rate


def build_dashboard_stats() -> DashboardStats:
    sessions = load_all_sessions()
    wallet = load_wallet()
    inventory = build_inventory_summary()
    summary = build_history_summary(sessions)
    best_weapon, best_weapon_rate = get_best_weapon(summary)
    last_session = sessions[-1] if sessions else None

    return DashboardStats(
        balance=int(wallet.get("balance", 0)),
        next_weapon=get_next_weapon(),
        total_sessions=summary.total_sessions,
        total_clean_hits=summary.total_clean_hits,
        total_valid_attempts=summary.total_valid_attempts,
        average_protocol_rate=summary.average_protocol_rate,
        best_weapon=best_weapon,
        best_weapon_rate=best_weapon_rate,
        best_session_id=summary.best_protocol_session_id,
        best_session_rate=summary.best_protocol_rate,
        last_session=last_session,
        today=build_today_stats(sessions),
        progress=build_player_progress(summary.total_clean_hits),
        inventory_weapon_count=int(inventory.get("weapon_count", 0)),
        owned_weapon_count=len(inventory.get("owned_weapons", [])),
        tracker=build_tracker_stats(),
    )
