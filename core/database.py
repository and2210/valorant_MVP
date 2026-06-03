from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from core.config import DATA_DIR

DB_FILE = DATA_DIR / "radiante.db"


def get_database_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DB_FILE


def connect() -> sqlite3.Connection:
    """
    Abre uma conexão SQLite local do Radiante.

    O banco fica em data/radiante.db. Essa camada é intencionalmente pequena:
    o objetivo da v0.20 é consolidar a fundação sem trocar toda a persistência
    do app de uma vez.
    """
    path = get_database_path()
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def execute(sql: str, parameters: Iterable | dict | None = None) -> None:
    with connect() as connection:
        connection.execute(sql, parameters or [])
        connection.commit()


def query_all(sql: str, parameters: Iterable | dict | None = None) -> list[sqlite3.Row]:
    with connect() as connection:
        cursor = connection.execute(sql, parameters or [])
        return list(cursor.fetchall())
