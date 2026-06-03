from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.database import get_database_path
from core.sqlite_store import rebuild_sqlite_from_current_files


def main() -> None:
    result = rebuild_sqlite_from_current_files()
    print("=" * 80)
    print("RADIANE SQLITE — REBUILD")
    print("=" * 80)
    print(f"Banco: {get_database_path()}")
    for key, value in result.items():
        print(f"{key}: {value}")
    print("=" * 80)
    print("Concluído.")


if __name__ == "__main__":
    main()
