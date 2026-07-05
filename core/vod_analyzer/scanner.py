from __future__ import annotations

import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .media_probe import probe_media
from .models import MediaInfo
from .paths import ensure_within


VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".m4v"}


def local_file_id(path: Path, chunk_size: int = 1024 * 1024) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
    with path.open("rb") as handle:
        digest.update(handle.read(chunk_size))
        if stat.st_size > chunk_size:
            handle.seek(max(stat.st_size - chunk_size, 0))
            digest.update(handle.read(chunk_size))
    return digest.hexdigest()[:24]


def is_file_stable(path: Path, minimum_age_seconds: float = 30.0) -> bool:
    stat = path.stat()
    return stat.st_size > 0 and time.time() - stat.st_mtime >= minimum_age_seconds


def scan_videos(
    root: Path,
    *,
    ffprobe: str = "ffprobe",
    minimum_age_seconds: float = 30.0,
    progress: Callable[[int, int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[MediaInfo]:
    root = ensure_within(root, root)
    input_root = ensure_within(root, root / "Entrada")
    if not input_root.exists():
        return []
    candidates = sorted(
        p for p in input_root.rglob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES
    )
    output: list[MediaInfo] = []
    for index, path in enumerate(candidates, 1):
        if cancelled and cancelled():
            break
        ensure_within(root, path)
        stat = path.stat()
        stable = is_file_stable(path, minimum_age_seconds)
        info = MediaInfo(
            path=path,
            file_id=local_file_id(path),
            size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_ctime).astimezone().isoformat(),
            modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
            stable=stable,
        )
        if stable:
            try:
                for key, value in probe_media(path, ffprobe).items():
                    setattr(info, key, value)
            except (OSError, RuntimeError) as exc:
                info.probe_error = str(exc)
        else:
            info.probe_error = "Arquivo ainda pode estar sendo gravado ou sincronizado."
        output.append(info)
        if progress:
            progress(index, len(candidates), path.name)
    return output
