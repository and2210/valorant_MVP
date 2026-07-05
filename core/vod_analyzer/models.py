from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MediaInfo:
    path: Path
    file_id: str
    size_bytes: int
    created_at: str
    modified_at: str
    duration_seconds: float = 0.0
    codec: str = "unknown"
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False
    stable: bool = True
    probe_error: str = ""

    def to_dict(self, root: Path | None = None) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path.relative_to(root)) if root else str(self.path)
        return data


@dataclass(slots=True)
class VodSession:
    session_id: str
    mode: str
    files: list[MediaInfo]
    warnings: list[str] = field(default_factory=list)
    confidence: float = 1.0

    @property
    def duration_seconds(self) -> float:
        return sum(item.duration_seconds for item in self.files)


@dataclass(frozen=True, slots=True)
class Region:
    x: int
    y: int
    width: int
    height: int

    def valid_for(self, frame_width: int, frame_height: int) -> bool:
        return (
            self.x >= 0 and self.y >= 0 and self.width > 0 and self.height > 0
            and self.x + self.width <= frame_width
            and self.y + self.height <= frame_height
        )


@dataclass(slots=True)
class OverlayCalibration:
    name: str
    width: int
    height: int
    regions: dict[str, Region]
    released_templates: dict[str, str]
    pressed_templates: dict[str, str]
    similarity_threshold: float = 0.72


@dataclass(slots=True)
class OverlayEvent:
    timestamp_ms: int
    event: str
    state: str
    confidence: float
    uncertain: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
