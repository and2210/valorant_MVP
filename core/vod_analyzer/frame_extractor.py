from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

from .paths import ensure_within


def extract_frame(path: Path, timestamp_seconds: float, ffmpeg: str = "ffmpeg") -> np.ndarray:
    command = [
        ffmpeg, "-v", "error", "-ss", f"{max(timestamp_seconds, 0):.3f}",
        "-i", str(path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
    ]
    completed = subprocess.run(command, capture_output=True, timeout=60, check=False)
    if completed.returncode != 0 or not completed.stdout:
        raise RuntimeError((completed.stderr.decode(errors="replace") or "FFmpeg frame extraction failed")[:1000])
    frame = cv2.imdecode(np.frombuffer(completed.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("FFmpeg returned an unreadable frame")
    return frame


def save_frame(frame: np.ndarray, root: Path, target: Path) -> Path:
    target = ensure_within(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite evidence: {target}")
    if not cv2.imwrite(str(target), frame):
        raise RuntimeError(f"Could not save frame: {target}")
    return target
