from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .frame_extractor import extract_frame, save_frame
from .models import OverlayEvent
from .paths import ensure_within


def build_evidence(
    root: Path,
    video: Path,
    events: list[OverlayEvent],
    report_dir: Path,
    *,
    ffmpeg: str = "ffmpeg",
    maximum_images: int = 40,
) -> list[str]:
    clicks = [event for event in events if event.event == "LMB" and event.state == "pressed" and not event.uncertain]
    selected = clicks[: max(maximum_images // 4, 0)]
    evidence_dir = ensure_within(root, report_dir / "evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    relative_paths: list[str] = []
    thumbnails: list[tuple[np.ndarray, str]] = []
    for event_index, event in enumerate(selected, 1):
        for suffix, offset_ms in (("before", -500), ("click", 0), ("after250", 250), ("after750", 750)):
            timestamp_ms = max(event.timestamp_ms + offset_ms, 0)
            frame = extract_frame(video, timestamp_ms / 1000.0, ffmpeg)
            name = f"event_{event_index:04d}_{suffix}_{timestamp_ms}ms.jpg"
            target = save_frame(frame, root, evidence_dir / name)
            relative_paths.append(str(target.relative_to(report_dir)).replace("\\", "/"))
            thumbnail = cv2.resize(frame, (320, 180))
            thumbnails.append((thumbnail, f"#{event_index} {timestamp_ms} ms | {suffix}"))
    if thumbnails:
        sheet = _contact_sheet(thumbnails)
        target = save_frame(sheet, root, report_dir / "contact_sheet_01.jpg")
        relative_paths.append(str(target.relative_to(report_dir)).replace("\\", "/"))
    return relative_paths


def _contact_sheet(items: list[tuple[np.ndarray, str]], columns: int = 3) -> np.ndarray:
    cell_width, cell_height = 320, 210
    rows = (len(items) + columns - 1) // columns
    sheet = np.full((rows * cell_height, columns * cell_width, 3), 24, dtype=np.uint8)
    for index, (image, label) in enumerate(items):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        sheet[y:y + 180, x:x + 320] = image
        cv2.putText(sheet, label, (x + 6, y + 199), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (240, 240, 240), 1, cv2.LINE_AA)
    return sheet
