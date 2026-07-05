from datetime import datetime
from pathlib import Path

import pytest

from core.vod_analyzer.markers import MarkerStore
from core.vod_analyzer.models import MediaInfo, OverlayEvent, VodSession
from core.vod_analyzer.timeline import (
    build_part_spans, correlate_timeline, create_analysis_windows,
    global_to_local, local_to_global,
)
from core.vod_analyzer.voice_transcriber import is_voice_marker


def ranked_session() -> VodSession:
    now = datetime.now().astimezone().isoformat()
    files = [
        MediaInfo(Path("Ranked_01_Parte-01.mp4"), "a", 1, now, now, duration_seconds=600, fps=30),
        MediaInfo(Path("Ranked_01_Parte-02.mp4"), "b", 1, now, now, duration_seconds=900, fps=30),
        MediaInfo(Path("Ranked_01_Parte-03.mp4"), "c", 1, now, now, duration_seconds=300, fps=30),
    ]
    return VodSession("Ranked_01", "ranked", files)


def dm_session() -> VodSession:
    session = ranked_session()
    return VodSession("DM_01", "dm", [session.files[0]])


def test_local_global_timestamp_conversion_across_ranked_parts() -> None:
    spans = build_part_spans(ranked_session())
    assert local_to_global(spans, 2, 42_000) == 642_000
    assert global_to_local(spans, 642_000) == (2, 42_000)
    # Exact boundary belongs to the next part in global lookup.
    assert global_to_local(spans, 600_000) == (2, 0)
    with pytest.raises(ValueError):
        local_to_global(spans, 1, 700_000)


def test_timeline_keeps_local_and_global_overlay_timestamps() -> None:
    timeline = correlate_timeline(
        ranked_session(),
        [(2, OverlayEvent(5_000, "LMB", "pressed", 0.98))],
    )
    shot = next(event for event in timeline["events"] if event["event_type"] == "shot_activation")
    assert shot["part_index"] == 2
    assert shot["local_timestamp_ms"] == 5_000
    assert shot["global_timestamp_ms"] == 605_000
    assert shot["source"] == "overlay_detector"
    assert shot["evidence_class"] == "fact"


def test_possible_duel_is_inference_not_fact() -> None:
    timeline = correlate_timeline(
        ranked_session(),
        [
            (1, OverlayEvent(10_000, "LMB", "pressed", 0.95)),
            (1, OverlayEvent(10_300, "LMB", "released", 0.95)),
            (1, OverlayEvent(11_000, "LMB", "pressed", 0.95)),
        ],
    )
    duel = next(event for event in timeline["events"] if event["event_type"] == "possible_duel")
    assert duel["evidence_class"] == "inference"
    assert duel["source"] == "shot_cluster_heuristic"


def test_dm_windows_require_explicit_marker_but_ranked_includes_duel() -> None:
    overlay = [(1, OverlayEvent(10_000, "LMB", "pressed", 0.95))]
    dm_timeline = correlate_timeline(dm_session(), overlay)
    assert create_analysis_windows(dm_timeline) == []

    marker = {
        "marker_id": "voice-1", "marker_type": "voice_marker", "part_index": 1,
        "local_timestamp_ms": 20_000, "text": "por que perdi esse duelo?",
        "source": "voice_transcription", "confidence": 0.9,
    }
    dm_marked = correlate_timeline(dm_session(), overlay, [marker])
    windows = create_analysis_windows(dm_marked, before_ms=3_000, after_ms=2_000)
    assert len(windows) == 1
    assert (windows[0].start_global_ms, windows[0].focus_global_ms, windows[0].end_global_ms) == (17_000, 20_000, 22_000)

    ranked_timeline = correlate_timeline(ranked_session(), overlay)
    assert any(window.reason == "possible_duel" for window in create_analysis_windows(ranked_timeline))


def test_window_can_cross_part_boundary() -> None:
    marker = {
        "marker_id": "round-1", "marker_type": "round_start", "part_index": 2,
        "local_timestamp_ms": 1_000, "text": "", "source": "manual", "confidence": 1.0,
    }
    timeline = correlate_timeline(ranked_session(), [], [marker])
    window = next(item for item in create_analysis_windows(timeline, before_ms=3_000, after_ms=2_000) if item.reason == "round_start")
    assert window.parts == (1, 2)


def test_marker_persistence_round_trip(tmp_path: Path) -> None:
    store = MarkerStore(tmp_path, "Ranked_01")
    marker = store.add(
        marker_type="round_start", part_index=2, local_timestamp_ms=42_000,
        text="início confirmado manualmente",
    )
    loaded = store.load()
    assert loaded == [marker]
    assert loaded[0]["source"] == "manual"
    assert str(store.path).startswith(str(tmp_path))


def test_voice_marker_terms_are_accent_insensitive() -> None:
    terms = ["por que", "analisar"]
    assert is_voice_marker("Por que eu perdi esse duelo?", terms) is True
    assert is_voice_marker("Quero analisar esta jogada", terms) is True
    assert is_voice_marker("inimigo no bomb B", terms) is False
