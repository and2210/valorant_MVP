from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SENSITIVE_TRACKED_PATHS = {
    "data/config.json",
    "data/radiante.db",
    ".env",
}
SENSITIVE_TRACKED_PREFIXES = {
    "data/tracker_raw/",
}
SENSITIVE_TRACKED_SUFFIXES = {
    ".spec",
}
SUSPICIOUS_PATTERNS = [
    re.compile(r"HDEV-[A-Za-z0-9-]{20,}"),
    re.compile(r"HENRIK_API_KEY[^\S\r\n]*=[^\S\r\n]*[^\s#]+"),
    re.compile(r'"api_key"\s*:\s*"[^"]{8,}"'),
]
SKIP_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".png",
    ".jpg",
    ".jpeg",
    ".ico",
}


def git_ls_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=False,
    )
    return [item.decode("utf-8", errors="replace") for item in result.stdout.split(b"\0") if item]


def is_sensitive_tracked(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized in SENSITIVE_TRACKED_PATHS:
        return True
    if any(normalized.startswith(prefix) for prefix in SENSITIVE_TRACKED_PREFIXES):
        return True
    if any(normalized.endswith(suffix) for suffix in SENSITIVE_TRACKED_SUFFIXES):
        return True
    if normalized.startswith("data/") and normalized.endswith(".csv") and "tracker" in normalized:
        return True
    return False


def has_suspicious_secret(path: str) -> bool:
    file_path = PROJECT_ROOT / path
    if file_path.suffix.lower() in SKIP_SUFFIXES:
        return False
    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(pattern.search(text) for pattern in SUSPICIOUS_PATTERNS)


def main() -> int:
    try:
        tracked = git_ls_files()
    except Exception as error:
        print(f"sensitive check: unsafe (git unavailable: {type(error).__name__})")
        return 1

    tracked_sensitive = [path for path in tracked if is_sensitive_tracked(path)]
    suspicious_files = [path for path in tracked if has_suspicious_secret(path)]

    if tracked_sensitive or suspicious_files:
        print("sensitive check: unsafe")
        for path in tracked_sensitive:
            print(f"tracked sensitive file: {path}")
        for path in suspicious_files:
            print(f"suspicious secret pattern: {path}")
        return 1

    print("sensitive check: safe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
