from __future__ import annotations

from core.database import connect, get_database_path

SCHEMA_VERSION = 2


def _table_columns(connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_column(connection, table_name: str, column_name: str, column_sql: str) -> None:
    if column_name not in _table_columns(connection, table_name):
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def initialize_database() -> None:
    """Cria/atualiza o banco local do Radiante."""
    get_database_path().parent.mkdir(parents=True, exist_ok=True)

    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS local_dm_sessions (
                session_id INTEGER PRIMARY KEY,
                identity_key TEXT UNIQUE NOT NULL,
                finished_at TEXT NOT NULL,
                started_at TEXT,
                weapon_used TEXT,
                clean_hits INTEGER NOT NULL DEFAULT 0,
                brake_errors INTEGER NOT NULL DEFAULT 0,
                diagonal_errors INTEGER NOT NULL DEFAULT 0,
                no_ad_errors INTEGER NOT NULL DEFAULT 0,
                valid_attempts INTEGER NOT NULL DEFAULT 0,
                protocol_rate REAL NOT NULL DEFAULT 0,
                kcreds_earned INTEGER NOT NULL DEFAULT 0,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_local_dm_sessions_finished_at
            ON local_dm_sessions(finished_at);

            CREATE INDEX IF NOT EXISTS idx_local_dm_sessions_weapon
            ON local_dm_sessions(weapon_used);

            CREATE TABLE IF NOT EXISTS tracker_dm_matches (
                match_id TEXT PRIMARY KEY,
                match_date TEXT NOT NULL,
                map_name TEXT,
                agent TEXT,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                linked_session_id INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_tracker_dm_matches_date
            ON tracker_dm_matches(match_date);

            CREATE TABLE IF NOT EXISTS tracker_ranked_matches (
                match_id TEXT PRIMARY KEY,
                match_date TEXT NOT NULL,
                map_name TEXT,
                agent TEXT,
                result TEXT,
                rr_change INTEGER NOT NULL DEFAULT 0,
                acs REAL NOT NULL DEFAULT 0,
                damage_delta INTEGER NOT NULL DEFAULT 0,
                fb_fd_delta INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_tracker_ranked_matches_date
            ON tracker_ranked_matches(match_date);

            CREATE TABLE IF NOT EXISTS wallet_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                balance INTEGER NOT NULL DEFAULT 0,
                next_weapon TEXT NOT NULL DEFAULT 'Classic',
                total_earned INTEGER NOT NULL DEFAULT 0,
                total_spent INTEGER NOT NULL DEFAULT 0,
                session_count INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS inventory_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                next_weapon TEXT NOT NULL DEFAULT 'Classic',
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_type TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                requested_start TEXT,
                requested_end TEXT,
                total_found INTEGER NOT NULL DEFAULT 0,
                total_inserted INTEGER NOT NULL DEFAULT 0,
                total_updated INTEGER NOT NULL DEFAULT 0,
                total_skipped INTEGER NOT NULL DEFAULT 0,
                error_message TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'henrik',
                mode TEXT NOT NULL DEFAULT '',
                scanned_count INTEGER NOT NULL DEFAULT 0,
                imported_count INTEGER NOT NULL DEFAULT 0,
                updated_count INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS henrik_raw_payloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                mode TEXT NOT NULL,
                match_id TEXT,
                riot_name TEXT,
                riot_tag TEXT,
                region TEXT,
                fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                UNIQUE(endpoint, mode, match_id, payload_hash)
            );

            CREATE INDEX IF NOT EXISTS idx_henrik_raw_payloads_match_id
            ON henrik_raw_payloads(match_id);

            CREATE INDEX IF NOT EXISTS idx_henrik_raw_payloads_fetched_at
            ON henrik_raw_payloads(fetched_at);
            """
        )

        for column_name, column_sql in [
            ("id", "id INTEGER"),
            ("import_type", "import_type TEXT NOT NULL DEFAULT ''"),
            ("requested_start", "requested_start TEXT"),
            ("requested_end", "requested_end TEXT"),
            ("total_found", "total_found INTEGER NOT NULL DEFAULT 0"),
            ("total_inserted", "total_inserted INTEGER NOT NULL DEFAULT 0"),
            ("total_updated", "total_updated INTEGER NOT NULL DEFAULT 0"),
            ("total_skipped", "total_skipped INTEGER NOT NULL DEFAULT 0"),
            ("error_message", "error_message TEXT NOT NULL DEFAULT ''"),
        ]:
            _ensure_column(connection, "import_runs", column_name, column_sql)

        import_run_columns = _table_columns(connection, "import_runs")
        if "id" in import_run_columns and "import_id" in import_run_columns:
            connection.execute(
                "UPDATE import_runs SET id = import_id WHERE id IS NULL AND import_id IS NOT NULL"
            )

        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        connection.commit()
