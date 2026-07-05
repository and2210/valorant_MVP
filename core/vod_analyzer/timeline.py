from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .models import OverlayEvent, VodSession


FACT = "fact"
INFERENCE = "inference"
UNCERTAINTY = "uncertainty"
RECOMMENDATION = "recommendation"


@dataclass(frozen=True, slots=True)
class PartSpan:
    part_index: int
    filename: str
    start_global_ms: int
    duration_ms: int

    @property
    def end_global_ms(self) -> int:
        return self.start_global_ms + self.duration_ms


@dataclass(slots=True)
class TimelineEvent:
    event_id: str
    event_type: str
    global_timestamp_ms: int
    local_timestamp_ms: int
    part_index: int
    part_filename: str
    confidence: float
    source: str
    evidence_class: str = FACT
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AnalysisWindow:
    window_id: str
    start_global_ms: int
    focus_global_ms: int
    end_global_ms: int
    reason: str
    source_event_ids: tuple[str, ...]
    confidence: float
    evidence_class: str
    parts: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_event_ids"] = list(self.source_event_ids)
        data["parts"] = list(self.parts)
        return data


def build_part_spans(session: VodSession) -> list[PartSpan]:
    spans: list[PartSpan] = []
    offset = 0
    for index, item in enumerate(session.files, 1):
        duration = max(round(item.duration_seconds * 1000), 0)
        spans.append(PartSpan(index, item.path.name, offset, duration))
        offset += duration
    return spans


def local_to_global(spans: list[PartSpan], part_index: int, local_timestamp_ms: int) -> int:
    span = _span(spans, part_index)
    if local_timestamp_ms < 0 or local_timestamp_ms > span.duration_ms:
        raise ValueError("Local timestamp outside part duration")
    return span.start_global_ms + local_timestamp_ms


def global_to_local(spans: list[PartSpan], global_timestamp_ms: int) -> tuple[int, int]:
    if not spans or global_timestamp_ms < 0 or global_timestamp_ms > spans[-1].end_global_ms:
        raise ValueError("Global timestamp outside session duration")
    for index, span in enumerate(spans):
        is_last = index == len(spans) - 1
        if global_timestamp_ms < span.end_global_ms or (is_last and global_timestamp_ms <= span.end_global_ms):
            return span.part_index, global_timestamp_ms - span.start_global_ms
    raise ValueError("Global timestamp could not be mapped")


def correlate_timeline(
    session: VodSession,
    overlay_by_part: Iterable[tuple[int, OverlayEvent]],
    markers: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    spans = build_part_spans(session)
    events: list[TimelineEvent] = []
    if spans:
        events.append(_event("session_start", 0, spans, 1.0, "session_manifest", FACT, {}))
    for span in spans:
        events.append(_event("part_start", span.start_global_ms, spans, 1.0, "session_manifest", FACT, {"part": span.part_index}, preferred_part=span.part_index))
        events.append(_event("part_end", span.end_global_ms, spans, 1.0, "session_manifest", FACT, {"part": span.part_index}, preferred_part=span.part_index))

    shot_events: list[TimelineEvent] = []
    for sequence, (part_index, event) in enumerate(overlay_by_part, 1):
        global_ms = local_to_global(spans, part_index, event.timestamp_ms)
        timeline_event = _event(
            f"overlay_{event.event.lower()}_{event.state}", global_ms, spans,
            event.confidence, "overlay_detector", UNCERTAINTY if event.uncertain else FACT,
            {"control": event.event, "state": event.state, "uncertain": event.uncertain},
            event_id=f"overlay-{part_index}-{sequence}",
        )
        events.append(timeline_event)
        if event.event == "LMB" and event.state == "pressed":
            shot = _event(
                "shot_activation", global_ms, spans, event.confidence, "overlay_detector",
                UNCERTAINTY if event.uncertain else FACT,
                {"derived_from": timeline_event.event_id}, event_id=f"shot-{part_index}-{sequence}",
            )
            events.append(shot)
            shot_events.append(shot)

    for marker in markers:
        part_index = int(marker["part_index"])
        local_ms = int(marker["local_timestamp_ms"])
        global_ms = local_to_global(spans, part_index, local_ms)
        marker_type = str(marker.get("marker_type") or "manual_note")
        source = str(marker.get("source") or "manual")
        confidence = float(marker.get("confidence", 1.0))
        evidence_class = FACT if confidence >= 0.7 else UNCERTAINTY
        end_local = marker.get("end_local_timestamp_ms")
        end_global = local_to_global(spans, part_index, int(end_local)) if end_local is not None else None
        events.append(_event(
            marker_type, global_ms, spans, confidence, source, evidence_class,
            {
                "text": str(marker.get("text") or ""),
                "end_local_timestamp_ms": end_local,
                "end_global_timestamp_ms": end_global,
                "marker_id": marker.get("marker_id"),
            },
            event_id=str(marker.get("marker_id") or f"marker-{len(events) + 1}"),
        ))

    events.extend(_possible_duels(shot_events, spans))
    if spans:
        events.append(_event("session_end", spans[-1].end_global_ms, spans, 1.0, "session_manifest", FACT, {}))
    events.sort(key=lambda item: (item.global_timestamp_ms, item.event_id))
    return {
        "schema_version": 1,
        "session_id": session.session_id,
        "mode": session.mode,
        "duration_ms": spans[-1].end_global_ms if spans else 0,
        "parts": [asdict(span) | {"end_global_ms": span.end_global_ms} for span in spans],
        "events": [event.to_dict() for event in events],
        "separation_policy": {
            FACT: "directly observed or user supplied",
            INFERENCE: "derived hypothesis requiring review",
            UNCERTAINTY: "insufficient confidence; manual review required",
            RECOMMENDATION: "not produced by the objective timeline",
        },
    }


def create_analysis_windows(
    timeline: dict[str, Any], *, before_ms: int = 3000, after_ms: int = 2000,
) -> list[AnalysisWindow]:
    duration = int(timeline.get("duration_ms") or 0)
    mode = str(timeline.get("mode") or "dm")
    events = timeline.get("events") or []
    selected: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        source = str(event.get("source") or "")
        is_explicit = source in {"manual", "voice_transcription"}
        if is_explicit or event_type in {"round_start", "round_end"}:
            selected.append(event)
        elif mode == "ranked" and event_type == "possible_duel":
            selected.append(event)
    windows: list[AnalysisWindow] = []
    for event in selected:
        focus = int(event["global_timestamp_ms"])
        start, end = max(focus - before_ms, 0), min(focus + after_ms, duration)
        part_ids = tuple(
            int(part["part_index"]) for part in timeline.get("parts", [])
            if start <= int(part["end_global_ms"]) and end >= int(part["start_global_ms"])
        )
        windows.append(AnalysisWindow(
            window_id=f"window-{event['event_id']}", start_global_ms=start,
            focus_global_ms=focus, end_global_ms=end,
            reason=str(event["event_type"]), source_event_ids=(str(event["event_id"]),),
            confidence=float(event.get("confidence", 0.0)),
            evidence_class=str(event.get("evidence_class") or UNCERTAINTY), parts=part_ids,
        ))
    return _merge_windows(windows)


def _possible_duels(shots: list[TimelineEvent], spans: list[PartSpan]) -> list[TimelineEvent]:
    if not shots:
        return []
    groups: list[list[TimelineEvent]] = [[shots[0]]]
    for shot in shots[1:]:
        if shot.global_timestamp_ms - groups[-1][-1].global_timestamp_ms <= 2500:
            groups[-1].append(shot)
        else:
            groups.append([shot])
    output: list[TimelineEvent] = []
    for index, group in enumerate(groups, 1):
        focus = group[0].global_timestamp_ms
        confidence = min(max(sum(item.confidence for item in group) / len(group) * 0.65, 0.0), 0.85)
        output.append(_event(
            "possible_duel", focus, spans, confidence, "shot_cluster_heuristic", INFERENCE,
            {"shot_count": len(group), "shot_event_ids": [item.event_id for item in group]},
            event_id=f"possible-duel-{index}",
        ))
    return output


def _merge_windows(windows: list[AnalysisWindow]) -> list[AnalysisWindow]:
    # Keep reasons distinct; overlapping windows may answer different explicit markers.
    seen: set[tuple[int, int, str]] = set()
    output: list[AnalysisWindow] = []
    for window in sorted(windows, key=lambda item: (item.start_global_ms, item.reason)):
        key = (window.start_global_ms, window.end_global_ms, window.reason)
        if key not in seen:
            output.append(window)
            seen.add(key)
    return output


def _event(
    event_type: str, global_ms: int, spans: list[PartSpan], confidence: float,
    source: str, evidence_class: str, data: dict[str, Any], event_id: str | None = None,
    preferred_part: int | None = None,
) -> TimelineEvent:
    if preferred_part is None:
        part_index, local_ms = global_to_local(spans, global_ms)
    else:
        part_index = preferred_part
        preferred_span = _span(spans, part_index)
        local_ms = global_ms - preferred_span.start_global_ms
    span = _span(spans, part_index)
    return TimelineEvent(
        event_id or f"{event_type}-{global_ms}", event_type, global_ms, local_ms,
        part_index, span.filename, max(0.0, min(float(confidence), 1.0)),
        source, evidence_class, data,
    )


def _span(spans: list[PartSpan], part_index: int) -> PartSpan:
    try:
        return next(span for span in spans if span.part_index == part_index)
    except StopIteration as exc:
        raise ValueError(f"Unknown part index: {part_index}") from exc
