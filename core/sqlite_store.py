from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from core.database import connect, get_database_path
from core.migrations import initialize_database
from core.models import DMResult


def _json_dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str) -> dict[str, Any]:
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _table_columns(connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _session_identity_key(session: DMResult) -> str:
    return "|".join([
        str(session.finished_at),
        str(session.weapon_used),
        str(session.clean_hits),
        str(session.brake_errors),
        str(session.diagonal_errors),
        str(session.no_ad_errors),
    ])


def initialize_sqlite_storage() -> Path:
    initialize_database()
    return get_database_path()


def count_rows(table_name: str) -> int:
    if table_name not in {
        "local_dm_sessions",
        "tracker_dm_matches",
        "tracker_ranked_matches",
        "henrik_raw_payloads",
        "import_runs",
        "wallet_state",
        "inventory_state",
    }:
        raise ValueError(f"Tabela não permitida: {table_name}")

    initialize_database()
    with connect() as connection:
        row = connection.execute(f"SELECT COUNT(*) AS total FROM {table_name}").fetchone()
        return int(row["total"] if row else 0)


def save_henrik_raw_payload(
    *,
    endpoint: str,
    mode: str,
    match_id: str,
    riot_name: str,
    riot_tag: str,
    region: str,
    payload: dict[str, Any],
) -> None:
    initialize_database()
    payload_json = _json_dumps(payload)
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    with connect() as connection:
        connection.execute(
            """
            INSERT INTO henrik_raw_payloads (
                endpoint, mode, match_id, riot_name, riot_tag, region, payload_json, payload_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint, mode, match_id, payload_hash) DO UPDATE SET
                fetched_at = CURRENT_TIMESTAMP,
                riot_name = excluded.riot_name,
                riot_tag = excluded.riot_tag,
                region = excluded.region,
                payload_json = excluded.payload_json
            """,
            (
                str(endpoint or ""),
                str(mode or ""),
                str(match_id or ""),
                str(riot_name or ""),
                str(riot_tag or ""),
                str(region or ""),
                payload_json,
                payload_hash,
            ),
        )
        connection.commit()


def start_import_run(
    *,
    import_type: str,
    requested_start: str = "",
    requested_end: str = "",
) -> int:
    initialize_database()
    with connect() as connection:
        columns = _table_columns(connection, "import_runs")
        connection.execute(
            """
            INSERT INTO import_runs (
                import_type, source, mode, requested_start, requested_end, status
            ) VALUES (?, 'henrik', ?, ?, ?, 'running')
            """,
            (
                str(import_type or ""),
                str(import_type or ""),
                str(requested_start or ""),
                str(requested_end or ""),
            ),
        )
        run_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        if "id" in columns:
            connection.execute("UPDATE import_runs SET id = ? WHERE rowid = ?", (run_id, run_id))
        connection.commit()
        return run_id


def finish_import_run(
    run_id: int,
    *,
    status: str,
    total_found: int = 0,
    total_inserted: int = 0,
    total_updated: int = 0,
    total_skipped: int = 0,
    error_message: str = "",
    scanned_count: int = 0,
    message: str = "",
) -> None:
    if run_id <= 0:
        return

    initialize_database()
    with connect() as connection:
        connection.execute(
            """
            UPDATE import_runs SET
                finished_at = CURRENT_TIMESTAMP,
                status = ?,
                total_found = ?,
                total_inserted = ?,
                total_updated = ?,
                total_skipped = ?,
                error_message = ?,
                scanned_count = ?,
                imported_count = ?,
                updated_count = ?,
                message = ?
            WHERE id = ? OR rowid = ?
            """,
            (
                str(status or ""),
                int(total_found or 0),
                int(total_inserted or 0),
                int(total_updated or 0),
                int(total_skipped or 0),
                str(error_message or "")[:1000],
                int(scanned_count or 0),
                int(total_inserted or 0),
                int(total_updated or 0),
                str(message or ""),
                int(run_id),
                int(run_id),
            ),
        )
        connection.commit()


def save_wallet_to_db(wallet: dict[str, Any]) -> None:
    initialize_database()
    payload = dict(wallet)
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO wallet_state (
                id, balance, next_weapon, total_earned, total_spent, session_count, payload_json, updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                balance = excluded.balance,
                next_weapon = excluded.next_weapon,
                total_earned = excluded.total_earned,
                total_spent = excluded.total_spent,
                session_count = excluded.session_count,
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                int(payload.get("balance") or 0),
                str(payload.get("next_weapon") or "Classic"),
                int(payload.get("total_earned") or 0),
                int(payload.get("total_spent") or 0),
                int(payload.get("session_count") or 0),
                _json_dumps(payload),
            ),
        )
        connection.commit()


def load_wallet_from_db() -> dict[str, Any] | None:
    initialize_database()
    with connect() as connection:
        row = connection.execute("SELECT payload_json FROM wallet_state WHERE id = 1").fetchone()

    if not row:
        return None

    return _json_loads(row["payload_json"])


def save_inventory_to_db(inventory: dict[str, Any]) -> None:
    initialize_database()
    payload = dict(inventory)
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO inventory_state (id, next_weapon, payload_json, updated_at)
            VALUES (1, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                next_weapon = excluded.next_weapon,
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (str(payload.get("next_weapon") or "Classic"), _json_dumps(payload)),
        )
        connection.commit()


def load_inventory_from_db() -> dict[str, Any] | None:
    initialize_database()
    with connect() as connection:
        row = connection.execute("SELECT payload_json FROM inventory_state WHERE id = 1").fetchone()

    if not row:
        return None

    return _json_loads(row["payload_json"])


def upsert_local_dm_session(session: DMResult) -> None:
    initialize_database()
    payload = session.to_dict()
    identity_key = _session_identity_key(session)

    with connect() as connection:
        connection.execute(
            """
            INSERT INTO local_dm_sessions (
                session_id, identity_key, finished_at, started_at, weapon_used,
                clean_hits, brake_errors, diagonal_errors, no_ad_errors,
                valid_attempts, protocol_rate, kcreds_earned, duration_seconds,
                payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id) DO UPDATE SET
                identity_key = excluded.identity_key,
                finished_at = excluded.finished_at,
                started_at = excluded.started_at,
                weapon_used = excluded.weapon_used,
                clean_hits = excluded.clean_hits,
                brake_errors = excluded.brake_errors,
                diagonal_errors = excluded.diagonal_errors,
                no_ad_errors = excluded.no_ad_errors,
                valid_attempts = excluded.valid_attempts,
                protocol_rate = excluded.protocol_rate,
                kcreds_earned = excluded.kcreds_earned,
                duration_seconds = excluded.duration_seconds,
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                int(session.session_id or 0),
                identity_key,
                session.finished_at,
                session.started_at,
                session.weapon_used,
                int(session.clean_hits),
                int(session.brake_errors),
                int(session.diagonal_errors),
                int(session.no_ad_errors),
                int(session.valid_attempts),
                float(session.protocol_rate),
                int(session.kcreds_earned),
                int(session.duration_seconds),
                _json_dumps(payload),
            ),
        )
        connection.commit()


def replace_local_dm_sessions(sessions: list[DMResult]) -> None:
    initialize_database()
    with connect() as connection:
        connection.execute("DELETE FROM local_dm_sessions")
        connection.commit()

    for session in sessions:
        upsert_local_dm_session(session)


def load_local_dm_sessions_from_db() -> list[DMResult]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            "SELECT payload_json FROM local_dm_sessions ORDER BY finished_at ASC, session_id ASC"
        ).fetchall()

    return [DMResult.from_dict(_json_loads(row["payload_json"])) for row in rows]


def _get_match_id(payload: dict[str, Any], prefix: str) -> str:
    match_id = str(payload.get("match_id") or "").strip()
    if match_id:
        return match_id
    return f"{prefix}-{payload.get('date', '')}-{payload.get('map_name', '')}-{payload.get('kills', 0)}-{payload.get('deaths', 0)}"


def upsert_tracker_dm_payload(payload: dict[str, Any]) -> None:
    initialize_database()
    match_id = _get_match_id(payload, "dm-no-id")
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO tracker_dm_matches (
                match_id, match_date, map_name, agent, duration_seconds, linked_session_id, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(match_id) DO UPDATE SET
                match_date = excluded.match_date,
                map_name = excluded.map_name,
                agent = excluded.agent,
                duration_seconds = excluded.duration_seconds,
                linked_session_id = excluded.linked_session_id,
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                match_id,
                str(payload.get("date") or ""),
                str(payload.get("map_name") or ""),
                str(payload.get("agent") or ""),
                int(payload.get("duration_seconds") or 0),
                int(payload.get("linked_session_id") or 0),
                _json_dumps(payload),
            ),
        )
        connection.commit()


def replace_tracker_dm_payloads(payloads: list[dict[str, Any]]) -> None:
    initialize_database()
    with connect() as connection:
        connection.execute("DELETE FROM tracker_dm_matches")
        connection.commit()

    for payload in payloads:
        upsert_tracker_dm_payload(payload)


def load_tracker_dm_payloads_from_db() -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            "SELECT payload_json FROM tracker_dm_matches ORDER BY match_date DESC, match_id DESC"
        ).fetchall()
    return [_json_loads(row["payload_json"]) for row in rows]


def upsert_tracker_ranked_payload(payload: dict[str, Any]) -> None:
    initialize_database()
    match_id = _get_match_id(payload, "ranked-no-id")
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO tracker_ranked_matches (
                match_id, match_date, map_name, agent, result, rr_change, acs,
                damage_delta, fb_fd_delta, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(match_id) DO UPDATE SET
                match_date = excluded.match_date,
                map_name = excluded.map_name,
                agent = excluded.agent,
                result = excluded.result,
                rr_change = excluded.rr_change,
                acs = excluded.acs,
                damage_delta = excluded.damage_delta,
                fb_fd_delta = excluded.fb_fd_delta,
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                match_id,
                str(payload.get("date") or ""),
                str(payload.get("map_name") or ""),
                str(payload.get("agent") or ""),
                str(payload.get("result") or ""),
                int(payload.get("rr_change") or 0),
                float(payload.get("acs") or 0),
                int(payload.get("damage_delta") or 0),
                int(payload.get("fb_fd_delta") or 0),
                _json_dumps(payload),
            ),
        )
        connection.commit()


def replace_tracker_ranked_payloads(payloads: list[dict[str, Any]]) -> None:
    initialize_database()
    with connect() as connection:
        connection.execute("DELETE FROM tracker_ranked_matches")
        connection.commit()

    for payload in payloads:
        upsert_tracker_ranked_payload(payload)


def load_tracker_ranked_payloads_from_db() -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            "SELECT payload_json FROM tracker_ranked_matches ORDER BY match_date DESC, match_id DESC"
        ).fetchall()
    return [_json_loads(row["payload_json"]) for row in rows]


def rebuild_sqlite_from_current_files() -> dict[str, int]:
    """
    Reconstrói o banco a partir dos arquivos atuais.

    Usado por scripts/dev e pela primeira abertura da v0.20. Não apaga CSV/JSON.
    """
    initialize_database()

    # Imports internos evitam ciclos durante startup.
    from core.persistence import (
        WALLET_FILE,
        default_wallet,
        load_all_sessions_from_files,
        load_json,
        normalize_wallet,
    )
    from core.inventory import INVENTORY_FILE, default_inventory, normalize_inventory
    from core.tracker_importer import TRACKER_DM_FILE, TRACKER_RANKED_FILE, TrackerDMMatch, TrackerRankedMatch
    import csv

    sessions = load_all_sessions_from_files()
    replace_local_dm_sessions(sessions)

    wallet = normalize_wallet(load_json(WALLET_FILE, default_wallet()))
    save_wallet_to_db(wallet)

    if INVENTORY_FILE.exists():
        try:
            with INVENTORY_FILE.open("r", encoding="utf-8") as file:
                inventory_raw = json.load(file)
        except json.JSONDecodeError:
            inventory_raw = default_inventory()
    else:
        inventory_raw = default_inventory()

    inventory = normalize_inventory(inventory_raw)
    save_inventory_to_db(inventory)

    dm_matches = []
    if TRACKER_DM_FILE.exists():
        with TRACKER_DM_FILE.open("r", newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file, delimiter=";")
            dm_matches = [TrackerDMMatch.from_dict(row) for row in reader if row]
    replace_tracker_dm_payloads([match.to_dict() for match in dm_matches])

    ranked_matches = []
    if TRACKER_RANKED_FILE.exists():
        with TRACKER_RANKED_FILE.open("r", newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file, delimiter=";")
            ranked_matches = [TrackerRankedMatch.from_dict(row) for row in reader if row]
    replace_tracker_ranked_payloads([match.to_dict() for match in ranked_matches])

    return {
        "local_dm_sessions": len(sessions),
        "tracker_dm_matches": len(dm_matches),
        "tracker_ranked_matches": len(ranked_matches),
        "wallet_state": 1,
        "inventory_state": 1,
    }


def ensure_sqlite_seeded_from_files() -> None:
    initialize_database()
    has_any_data = any([
        count_rows("local_dm_sessions") > 0,
        count_rows("tracker_dm_matches") > 0,
        count_rows("tracker_ranked_matches") > 0,
        count_rows("wallet_state") > 0,
        count_rows("inventory_state") > 0,
    ])

    if not has_any_data:
        rebuild_sqlite_from_current_files()
