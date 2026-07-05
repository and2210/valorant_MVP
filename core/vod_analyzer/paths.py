from __future__ import annotations

import re
import shutil
import os
from pathlib import Path


SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_within(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"Path outside configured VOD root: {candidate}")
    return resolved


def safe_name(value: str) -> str:
    cleaned = SAFE_NAME.sub("_", value.strip()).strip("._")
    return cleaned or "session"


def create_vod_structure(root: Path) -> None:
    for relative in (
        "Entrada/DM", "Entrada/Ranked", "Processados/DM", "Processados/Ranked",
        "Relatorios", "Cache", "Logs",
    ):
        ensure_within(root, root / relative).mkdir(parents=True, exist_ok=True)


def resolve_media_tool(configured: str, executable: str) -> str:
    """Resolve configured/PATH tools, including Winget installs before shell restart."""
    configured_path = Path(configured).expanduser()
    if configured_path.is_file():
        return str(configured_path.resolve())
    found = shutil.which(configured)
    if found:
        return found
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    package_root = local_app_data / "Microsoft" / "WinGet" / "Packages"
    matches = sorted(package_root.glob(f"Gyan.FFmpeg_*/*/bin/{executable}.exe"), reverse=True)
    if matches:
        return str(matches[0])
    return configured
