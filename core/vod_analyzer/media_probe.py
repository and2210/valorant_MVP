from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def parse_fps(value: str | None) -> float:
    if not value or value in {"0/0", "N/A"}:
        return 0.0
    try:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        return 0.0


def parse_probe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = any(s.get("codec_type") == "audio" for s in streams)
    fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    try:
        duration = float(fmt.get("duration") or video.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "duration_seconds": max(duration, 0.0),
        "codec": str(video.get("codec_name") or "unknown"),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "has_audio": audio,
    }


def probe_media(path: Path, ffprobe: str = "ffprobe", timeout: int = 45) -> dict[str, Any]:
    command = [
        ffprobe, "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        message = (completed.stderr or "FFprobe failed").strip()
        raise RuntimeError(message[:1000])
    try:
        return parse_probe_payload(json.loads(completed.stdout))
    except json.JSONDecodeError as exc:
        raise RuntimeError("FFprobe returned invalid JSON") from exc
