from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from core.models import DMResult
from core.persistence import load_all_sessions


@dataclass
class HistorySummary:
    total_sessions: int = 0
    total_clean_hits: int = 0
    total_brake_errors: int = 0
    total_diagonal_errors: int = 0
    total_no_ad_errors: int = 0
    total_valid_attempts: int = 0
    total_kcreds_earned: int = 0
    average_protocol_rate: float = 0.0
    best_protocol_rate: float = 0.0
    best_protocol_session_id: int = 0
    best_protocol_weapon: str = ""
    best_clean_hits: int = 0
    best_clean_hits_session_id: int = 0
    best_clean_hits_weapon: str = ""
    sessions_by_weapon: dict[str, int] = field(default_factory=dict)
    average_protocol_by_weapon: dict[str, float] = field(default_factory=dict)


def build_history_summary(sessions: list[DMResult] | None = None) -> HistorySummary:
    sessions = sessions if sessions is not None else load_all_sessions()

    summary = HistorySummary(total_sessions=len(sessions))

    if not sessions:
        return summary

    protocol_sum = 0.0
    protocol_count = 0
    weapon_counts: dict[str, int] = defaultdict(int)
    weapon_protocol_sum: dict[str, float] = defaultdict(float)
    weapon_protocol_count: dict[str, int] = defaultdict(int)

    for session in sessions:
        summary.total_clean_hits += session.clean_hits
        summary.total_brake_errors += session.brake_errors
        summary.total_diagonal_errors += session.diagonal_errors
        summary.total_no_ad_errors += session.no_ad_errors
        summary.total_valid_attempts += session.valid_attempts
        summary.total_kcreds_earned += session.kcreds_earned

        weapon_counts[session.weapon_used] += 1

        if session.has_attempts:
            protocol_sum += session.protocol_rate
            protocol_count += 1
            weapon_protocol_sum[session.weapon_used] += session.protocol_rate
            weapon_protocol_count[session.weapon_used] += 1

        if session.protocol_rate > summary.best_protocol_rate:
            summary.best_protocol_rate = session.protocol_rate
            summary.best_protocol_session_id = session.session_id
            summary.best_protocol_weapon = session.weapon_used

        if session.clean_hits > summary.best_clean_hits:
            summary.best_clean_hits = session.clean_hits
            summary.best_clean_hits_session_id = session.session_id
            summary.best_clean_hits_weapon = session.weapon_used

    if protocol_count > 0:
        summary.average_protocol_rate = round(protocol_sum / protocol_count, 1)

    summary.sessions_by_weapon = dict(sorted(weapon_counts.items()))

    for weapon, count in weapon_protocol_count.items():
        if count > 0:
            summary.average_protocol_by_weapon[weapon] = round(weapon_protocol_sum[weapon] / count, 1)

    summary.average_protocol_by_weapon = dict(sorted(summary.average_protocol_by_weapon.items()))

    return summary


def get_recent_sessions(limit: int = 5) -> list[DMResult]:
    sessions = load_all_sessions()
    return list(reversed(sessions[-limit:]))
