import numpy as np

from core.vod_analyzer.metrics import calculate_metrics
from core.vod_analyzer.models import OverlayEvent
from core.vod_analyzer.overlay_detector import classify_state, transitions_from_samples


def test_pressed_released_transitions() -> None:
    samples = [
        (0, {"A": ("released", 0.99)}),
        (33, {"A": ("pressed", 0.98)}),
        (66, {"A": ("pressed", 0.98)}),
        (99, {"A": ("released", 0.97)}),
    ]
    events = transitions_from_samples(samples)
    assert [(event.timestamp_ms, event.state) for event in events] == [(33, "pressed"), (99, "released")]


def test_template_classification() -> None:
    released = np.zeros((8, 8, 3), dtype=np.uint8)
    pressed = np.full((8, 8, 3), 255, dtype=np.uint8)
    state, confidence = classify_state(pressed.copy(), released, pressed)
    assert state == "pressed"
    assert confidence >= 0.9


def test_ad_to_lmb_metrics_and_temporal_resolution() -> None:
    events = [
        OverlayEvent(0, "A", "pressed", 0.99),
        OverlayEvent(200, "A", "released", 0.99),
        OverlayEvent(266, "LMB", "pressed", 0.99),
        OverlayEvent(366, "LMB", "released", 0.99),
    ]
    metrics = calculate_metrics(events, 30)
    assert metrics["movement_to_lmb_intervals_ms"] == [66]
    assert metrics["temporal_resolution_ms"] == 33
    assert metrics["possible_incomplete_stop"] is True
