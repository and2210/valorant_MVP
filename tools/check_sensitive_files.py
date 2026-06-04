from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_PATTERNS = [
    ".env",
    "data/",
    "build/",
    "dist/",
    "__pycache__/",
]
FORBIDDEN_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
}
FORBIDDEN_NAMES = {
    "wallet.json",
    "sessions.csv",
    "inventory.json",
}
FORBIDDEN_SEGMENTS = {
    "tracker_raw",
    "input_audit",
    "__pycache__",
}


def git_ls_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def is_forbidden(path_text: str) -> bool:
    normalized = path_text.replace("\\", "/")
    path = Path(normalized)

    if normalized == ".env":
        return True
    if normalized.startswith("data/"):
        return True
    if normalized.startswith("build/") or normalized.startswith("dist/"):
        return True
    if "__pycache__/" in f"{normalized}/":
        return True
    if path.name in FORBIDDEN_NAMES:
        return True
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return True
    if any(segment in FORBIDDEN_SEGMENTS for segment in path.parts):
        return True

    return False


def main() -> int:
    tracked_files = git_ls_files()
    violations = [path for path in tracked_files if is_forbidden(path)]

    if violations:
        print("sensitive check: failed")
        for path in violations:
            print(path)
        return 1

    print("sensitive check: safe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
