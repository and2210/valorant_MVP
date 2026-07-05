from __future__ import annotations

from collections import Counter
from typing import Any

from .models import OverlayEvent


def calculate_metrics(events: list[OverlayEvent], fps: float = 30.0) -> dict[str, Any]:
    ordered = sorted(events, key=lambda event: event.timestamp_ms)
    states = {"A": "released", "D": "released", "LMB": "released"}
    pressed_at: dict[str, int] = {}
    releases: dict[str, int] = {}
    durations: dict[str, list[int]] = {"A": [], "D": [], "LMB": []}
    movement_fire_overlaps = 0
    movement_to_fire_ms: list[int] = []
    uncertain = 0
    counts: Counter[str] = Counter()
    lmb_press_times: list[int] = []
    for event in ordered:
        counts[f"{event.event}_{event.state}"] += 1
        uncertain += int(event.uncertain)
        states[event.event] = event.state
        if event.state == "pressed":
            pressed_at[event.event] = event.timestamp_ms
            if event.event == "LMB":
                lmb_press_times.append(event.timestamp_ms)
                if states["A"] == "pressed" or states["D"] == "pressed":
                    movement_fire_overlaps += 1
                prior = [value for value in releases.values() if value <= event.timestamp_ms]
                if prior:
                    movement_to_fire_ms.append(event.timestamp_ms - max(prior))
        else:
            start = pressed_at.pop(event.event, None)
            if start is not None:
                durations[event.event].append(max(event.timestamp_ms - start, 0))
            if event.event in {"A", "D"}:
                releases[event.event] = event.timestamp_ms
    rapid_lmb = sum(1 for first, second in zip(lmb_press_times, lmb_press_times[1:]) if second - first <= 300)
    return {
        "temporal_resolution_ms": round(1000.0 / fps) if fps > 0 else None,
        "event_count": len(ordered),
        "counts": dict(counts),
        "press_durations_ms": durations,
        "movement_fire_overlap_count": movement_fire_overlaps,
        "movement_to_lmb_intervals_ms": movement_to_fire_ms,
        "average_movement_to_lmb_ms": round(sum(movement_to_fire_ms) / len(movement_to_fire_ms), 1) if movement_to_fire_ms else None,
        "rapid_lmb_reactivation_count": rapid_lmb,
        "long_lmb_count": sum(duration >= 500 for duration in durations["LMB"]),
        "ad_alternation_count": _alternations(ordered),
        "uncertain_event_count": uncertain,
        "possible_shooting_while_moving": movement_fire_overlaps > 0,
        "possible_incomplete_stop": any(value < 100 for value in movement_to_fire_ms),
        "possible_long_burst": any(value >= 500 for value in durations["LMB"]),
        "possible_reconfirmation": rapid_lmb > 0,
        "uncertain_event": uncertain > 0,
    }


def _alternations(events: list[OverlayEvent]) -> int:
    presses = [event.event for event in events if event.event in {"A", "D"} and event.state == "pressed"]
    return sum(first != second for first, second in zip(presses, presses[1:]))
