from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import ensure_within


VALID_MARKER_TYPES = {"manual_note", "voice_marker", "round_start", "round_end", "possible_duel_review"}


class MarkerStore:
    def __init__(self, root: Path, session_id: str) -> None:
        self.root = root.resolve()
        self.path = ensure_within(self.root, self.root / "Cache" / "markers" / f"{session_id}.json")

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        markers = payload.get("markers", []) if isinstance(payload, dict) else []
        return [item for item in markers if isinstance(item, dict)]

    def add(
        self, *, marker_type: str, part_index: int, local_timestamp_ms: int,
        text: str = "", source: str = "manual", confidence: float = 1.0,
        end_local_timestamp_ms: int | None = None,
    ) -> dict[str, Any]:
        if marker_type not in VALID_MARKER_TYPES:
            raise ValueError(f"Unsupported marker type: {marker_type}")
        marker = {
            "marker_id": f"marker-{uuid.uuid4().hex}",
            "marker_type": marker_type,
            "part_index": int(part_index),
            "local_timestamp_ms": int(local_timestamp_ms),
            "end_local_timestamp_ms": int(end_local_timestamp_ms) if end_local_timestamp_ms is not None else None,
            "text": str(text),
            "source": str(source),
            "confidence": max(0.0, min(float(confidence), 1.0)),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        markers = self.load()
        markers.append(marker)
        self.save(markers)
        return marker

    def save(self, markers: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"schema_version": 1, "markers": markers}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
