from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import core.database as database
from core.migrations import initialize_database
from core.sqlite_store import (
    finish_import_run,
    save_henrik_raw_payload,
    start_import_run,
    upsert_tracker_dm_payload,
    upsert_tracker_ranked_payload,
)


def count_rows(db_path: Path, table_name: str) -> int:
    with sqlite3.connect(db_path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def validate() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "radiante_test.db"
        database.DB_FILE = db_path

        initialize_database()

        payload = {
            "metadata": {"match_id": "match-raw-1"},
            "players": [],
            "kills": [],
        }
        save_henrik_raw_payload(
            endpoint="valorant/v4/matches",
            mode="ranked",
            match_id="match-raw-1",
            riot_name="Player",
            riot_tag="TAG",
            region="br",
            payload=payload,
        )
        save_henrik_raw_payload(
            endpoint="valorant/v4/matches",
            mode="ranked",
            match_id="match-raw-1",
            riot_name="Player",
            riot_tag="TAG",
            region="br",
            payload=payload,
        )
        assert count_rows(db_path, "henrik_raw_payloads") == 1

        run_id = start_import_run(import_type="ranked", requested_start="2026-06-03", requested_end="2026-06-03")
        finish_import_run(
            run_id,
            status="success",
            total_found=1,
            total_inserted=1,
            total_updated=0,
            total_skipped=0,
            scanned_count=1,
            message="validation",
        )
        assert count_rows(db_path, "import_runs") == 1

        upsert_tracker_ranked_payload({"match_id": "ranked-1", "date": "2026-06-03", "agent": "Omen"})
        upsert_tracker_ranked_payload({"match_id": "ranked-1", "date": "2026-06-03", "agent": "Omen"})
        upsert_tracker_dm_payload({"match_id": "dm-1", "date": "2026-06-03", "agent": "Iso"})
        upsert_tracker_dm_payload({"match_id": "dm-1", "date": "2026-06-03", "agent": "Iso"})
        assert count_rows(db_path, "tracker_ranked_matches") == 1
        assert count_rows(db_path, "tracker_dm_matches") == 1

    print("henrik sqlite validation: ok")


if __name__ == "__main__":
    validate()
