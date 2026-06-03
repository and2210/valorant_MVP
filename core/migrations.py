from __future__ import annotations

from core.database import connect, get_database_path

SCHEMA_VERSION = 1


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
                import_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                mode TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                scanned_count INTEGER NOT NULL DEFAULT 0,
                imported_count INTEGER NOT NULL DEFAULT 0,
                updated_count INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT ''
            );
            """
        )

        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        connection.commit()
