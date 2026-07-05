from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from .models import OverlayCalibration, Region
from .paths import ensure_within, safe_name


def crop_region(frame: np.ndarray, region: Region) -> np.ndarray:
    height, width = frame.shape[:2]
    if not region.valid_for(width, height):
        raise ValueError("Overlay region is outside the calibration frame")
    return frame[region.y:region.y + region.height, region.x:region.x + region.width].copy()


def save_calibration(
    root: Path,
    name: str,
    released_frame: np.ndarray,
    pressed_frames: dict[str, np.ndarray],
    regions: dict[str, Region],
    threshold: float = 0.72,
) -> Path:
    height, width = released_frame.shape[:2]
    cache_dir = ensure_within(root, root / "Cache" / "calibrations" / safe_name(name))
    if cache_dir.exists():
        raise FileExistsError("Calibration already exists; choose a new layout name.")
    cache_dir.mkdir(parents=True)
    released_templates: dict[str, str] = {}
    pressed_templates: dict[str, str] = {}
    for key in ("A", "D", "LMB"):
        region = regions[key]
        released_name = f"{key.lower()}_released.png"
        pressed_name = f"{key.lower()}_pressed.png"
        cv2.imwrite(str(cache_dir / released_name), crop_region(released_frame, region))
        cv2.imwrite(str(cache_dir / pressed_name), crop_region(pressed_frames[key], region))
        released_templates[key] = released_name
        pressed_templates[key] = pressed_name
    calibration = OverlayCalibration(
        name=name, width=width, height=height, regions=regions,
        released_templates=released_templates, pressed_templates=pressed_templates,
        similarity_threshold=threshold,
    )
    payload = asdict(calibration)
    (cache_dir / "calibration.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return cache_dir / "calibration.json"


def load_calibration(root: Path, calibration_file: Path) -> tuple[OverlayCalibration, dict[str, np.ndarray], dict[str, np.ndarray]]:
    path = ensure_within(root, calibration_file)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["regions"] = {key: Region(**value) for key, value in payload["regions"].items()}
    calibration = OverlayCalibration(**payload)
    released = {key: cv2.imread(str(path.parent / value)) for key, value in calibration.released_templates.items()}
    pressed = {key: cv2.imread(str(path.parent / value)) for key, value in calibration.pressed_templates.items()}
    if any(image is None for image in [*released.values(), *pressed.values()]):
        raise RuntimeError("Calibration template is missing or invalid")
    return calibration, released, pressed
