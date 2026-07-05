from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .models import MediaInfo, VodSession
from .paths import safe_name


PART_PATTERN = re.compile(r"(?i)(?:parte|part)[-_ ]?(\d+)")
DM_NAME_PATTERN = re.compile(r"(?i)^DM[_-]\d{4}-\d{2}-\d{2}[_-]\d+$")


def part_number(path: Path) -> int | None:
    match = PART_PATTERN.search(path.stem)
    return int(match.group(1)) if match else None


def classify_mode(item: MediaInfo) -> str:
    parts = {part.lower() for part in item.path.parts}
    name = item.path.name.lower()
    if "ranked" in parts or "ranked" in name or part_number(item.path) is not None:
        return "ranked"
    return "dm"


def _ranked_key(item: MediaInfo) -> str:
    if item.path.parent.name.lower() not in {"ranked", "entrada"}:
        return safe_name(item.path.parent.name)
    stem = PART_PATTERN.sub("", item.path.stem).rstrip("-_ ")
    return safe_name(stem)


def _dm_key(item: MediaInfo, index: int) -> str:
    stem = safe_name(item.path.stem)
    if DM_NAME_PATTERN.match(stem):
        return stem
    day = datetime.fromisoformat(item.created_at).strftime("%Y-%m-%d")
    return f"DM_{day}_{index:02d}"


def group_sessions(items: list[MediaInfo]) -> list[VodSession]:
    duplicates: dict[str, list[MediaInfo]] = defaultdict(list)
    for item in items:
        duplicates[item.file_id].append(item)

    ranked: dict[str, list[MediaInfo]] = defaultdict(list)
    sessions: list[VodSession] = []
    daily_dm_counts: dict[str, int] = defaultdict(int)
    for item in sorted(items, key=lambda value: (value.created_at, str(value.path).lower())):
        if classify_mode(item) == "ranked":
            ranked[_ranked_key(item)].append(item)
            continue
        day = datetime.fromisoformat(item.created_at).strftime("%Y-%m-%d")
        daily_dm_counts[day] += 1
        warnings = []
        if len(duplicates[item.file_id]) > 1:
            warnings.append("Possível duplicata detectada pelo identificador local.")
        if not item.stable or item.probe_error:
            warnings.append(item.probe_error or "Arquivo instável.")
        sessions.append(VodSession(_dm_key(item, daily_dm_counts[day]), "dm", [item], warnings, 1.0 if not warnings else 0.6))

    for key, files in ranked.items():
        files.sort(key=lambda item: (part_number(item.path) or 10_000, item.created_at))
        warnings: list[str] = []
        numbers = [number for item in files if (number := part_number(item.path)) is not None]
        if numbers:
            expected = list(range(1, max(numbers) + 1))
            missing = sorted(set(expected) - set(numbers))
            repeated = sorted(number for number in set(numbers) if numbers.count(number) > 1)
            if missing:
                warnings.append("Partes ausentes: " + ", ".join(f"Parte-{n:02d}" for n in missing))
            if repeated:
                warnings.append("Partes repetidas: " + ", ".join(str(n) for n in repeated))
        else:
            warnings.append("Ordem inferida por data; nomes de Parte-NN não encontrados.")
        if any(len(duplicates[item.file_id]) > 1 for item in files):
            warnings.append("Possível duplicata detectada pelo identificador local.")
        if any(not item.stable or item.probe_error for item in files):
            warnings.append("Uma ou mais partes estão instáveis ou sem metadados válidos.")
        sessions.append(VodSession(key, "ranked", files, warnings, 1.0 if not warnings else 0.6))
    return sorted(sessions, key=lambda session: session.files[0].created_at if session.files else "")
