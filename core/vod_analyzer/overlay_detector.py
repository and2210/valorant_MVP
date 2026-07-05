from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import cv2
import numpy as np

from .models import OverlayCalibration, OverlayEvent
from .overlay_calibration import crop_region, load_calibration


def normalized_similarity(image: np.ndarray, template: np.ndarray) -> float:
    if image.shape[:2] != template.shape[:2]:
        image = cv2.resize(image, (template.shape[1], template.shape[0]))
    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    difference = cv2.absdiff(image_gray, template_gray)
    return max(0.0, min(1.0, 1.0 - float(np.mean(difference)) / 255.0))


def classify_state(image: np.ndarray, released: np.ndarray, pressed: np.ndarray) -> tuple[str, float]:
    released_score = normalized_similarity(image, released)
    pressed_score = normalized_similarity(image, pressed)
    state = "pressed" if pressed_score > released_score else "released"
    best = max(released_score, pressed_score)
    separation = abs(pressed_score - released_score)
    # Similar templates are inherently ambiguous even when both match well.
    confidence = max(0.0, min(1.0, best * 0.55 + separation * 0.45))
    return state, confidence


def transitions_from_samples(
    samples: list[tuple[int, dict[str, tuple[str, float]]]], threshold: float = 0.72,
) -> list[OverlayEvent]:
    previous: dict[str, str] = {}
    events: list[OverlayEvent] = []
    for timestamp_ms, states in samples:
        for key, (state, confidence) in states.items():
            if key not in previous:
                previous[key] = state
                continue
            if previous[key] != state:
                events.append(OverlayEvent(timestamp_ms, key, state, confidence, confidence < threshold))
                previous[key] = state
    return events


def iter_video_samples(
    path: Path,
    calibration: OverlayCalibration,
    released: dict[str, np.ndarray],
    pressed: dict[str, np.ndarray],
    cancelled: Callable[[], bool] | None = None,
) -> Iterator[tuple[int, dict[str, tuple[str, float]]]]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open video: {path.name}")
    try:
        while True:
            if cancelled and cancelled():
                return
            ok, frame = capture.read()
            if not ok:
                return
            if frame.shape[1] != calibration.width or frame.shape[0] != calibration.height:
                raise RuntimeError("Video resolution does not match overlay calibration")
            states = {
                key: classify_state(crop_region(frame, region), released[key], pressed[key])
                for key, region in calibration.regions.items()
            }
            yield int(capture.get(cv2.CAP_PROP_POS_MSEC)), states
    finally:
        capture.release()


def detect_overlay_events(
    root: Path, video: Path, calibration_file: Path,
    cancelled: Callable[[], bool] | None = None,
) -> list[OverlayEvent]:
    calibration, released, pressed = load_calibration(root, calibration_file)
    return transitions_from_samples(
        list(iter_video_samples(video, calibration, released, pressed, cancelled)),
        calibration.similarity_threshold,
    )
