from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from core.config import (
    DATA_DIR,
    SESSIONS_FILE,
    WALLET_FILE,
    load_config,
)
from core.models import DMResult
from core.sqlite_store import (
    load_local_dm_sessions_from_db,
    load_wallet_from_db,
    save_wallet_to_db,
    upsert_local_dm_session,
)

SESSION_HEADERS = [
    "session_id",
    "datetime",
    "started_at",
    "finished_at",
    "duration_seconds",
    "weapon_used",
    "clean_hits",
    "brake_errors",
    "diagonal_errors",
    "no_ad_errors",
    "valid_attempts",
    "ignored_clicks",
    "clicks_while_holding_lateral",
    "protocol_rate",
    "kcreds_earned",
    "balance_before",
    "balance_after_earning",
    "weapon_bought_next",
    "weapon_cost",
    "balance_final",
    "input_key_presses",
    "input_mouse_presses",
    "input_scroll_events",
    "input_scroll_jump_events",
    "input_fire_taps",
    "input_fire_bursts",
    "input_fire_long_sprays",
    "input_fire_events",
    "input_average_fire_seconds",
    "input_max_fire_seconds",
    "input_shots_while_forward",
    "input_shots_with_crouch",
    "input_crouch_fire_long_count",
    "input_diagonal_entries",
    "input_diagonal_seconds",
]


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def default_wallet() -> dict:
    config = load_config()

    return {
        "balance": config.default_starting_balance,
        "next_weapon": config.default_next_weapon,
        "total_earned": 0,
        "total_spent": 0,
        "session_count": 0,
        "sessions": [],
    }


def normalize_wallet(wallet: dict) -> dict:
    config = load_config()

    wallet.setdefault("balance", config.default_starting_balance)
    wallet.setdefault("next_weapon", config.default_next_weapon)
    wallet.setdefault("total_earned", 0)
    wallet.setdefault("total_spent", 0)
    wallet.setdefault("sessions", [])
    wallet.setdefault("session_count", len(wallet.get("sessions", [])))
    wallet["balance"] = max(int(wallet.get("balance", 0)), 0)
    wallet["total_earned"] = max(int(wallet.get("total_earned", 0)), 0)
    wallet["total_spent"] = max(int(wallet.get("total_spent", 0)), 0)
    wallet["session_count"] = max(int(wallet.get("session_count", 0)), 0)
    return wallet


def load_json(path: Path, fallback: dict) -> dict:
    ensure_data_dir()

    if not path.exists():
        save_json(path, fallback)
        return dict(fallback)

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError:
        data = dict(fallback)
        save_json(path, data)

    return data


def save_json(path: Path, data: dict) -> None:
    ensure_data_dir()

    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def load_wallet() -> dict:
    db_wallet = load_wallet_from_db()

    if db_wallet is not None:
        return normalize_wallet(db_wallet)

    wallet = load_json(WALLET_FILE, default_wallet())
    normalized = normalize_wallet(wallet)
    save_wallet_to_db(normalized)
    return normalized


def save_wallet(wallet: dict) -> None:
    normalized = normalize_wallet(wallet)
    save_json(WALLET_FILE, normalized)
    save_wallet_to_db(normalized)


def result_to_dict(result: DMResult | dict[str, Any]) -> dict:
    if isinstance(result, DMResult):
        return result.to_dict()

    return dict(result)


def append_session_to_csv(result: DMResult | dict[str, Any]) -> None:
    ensure_data_dir()
    file_exists = SESSIONS_FILE.exists()
    session_data = result_to_dict(result)

    with SESSIONS_FILE.open("a", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=SESSION_HEADERS, delimiter=";")

        if not file_exists:
            writer.writeheader()

        writer.writerow({header: session_data.get(header, "") for header in SESSION_HEADERS})

    upsert_local_dm_session(DMResult.from_dict(session_data))


def load_sessions_from_csv() -> list[DMResult]:
    ensure_data_dir()

    if not SESSIONS_FILE.exists():
        return []

    with SESSIONS_FILE.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file, delimiter=";")
        return [DMResult.from_dict(row) for row in reader if row]


def load_sessions_from_wallet_history(wallet: dict | None = None) -> list[DMResult]:
    wallet = normalize_wallet(wallet or load_wallet())
    sessions = wallet.get("sessions", [])

    if not isinstance(sessions, list):
        return []

    return [DMResult.from_dict(item) for item in sessions if isinstance(item, dict)]


def session_identity(session: DMResult) -> tuple[str, str, int, int, int, int]:
    """
    Chave lógica para detectar a mesma sessão vindo de fontes diferentes.

    A versão antiga do wallet.json não tinha session_id. Por isso a deduplicação
    não pode depender somente do ID; usamos horário, arma e contadores principais.
    """
    return (
        session.finished_at,
        session.weapon_used,
        session.clean_hits,
        session.brake_errors,
        session.diagonal_errors,
        session.no_ad_errors,
    )


def assign_stable_session_ids(sessions: list[DMResult]) -> list[DMResult]:
    """
    Garante IDs estáveis e legíveis para sessões antigas migradas.

    Regras:
    - IDs positivos já existentes são preservados sempre que possível.
    - Sessões antigas com session_id 0 recebem ID pela ordem cronológica.
    - Se houver colisão de ID, a sessão mais nova recebe o próximo ID livre.

    Isso corrige o histórico antigo que aparecia como #0 no F8 sem alterar
    o formato dos arquivos atuais.
    """
    ordered_sessions = sorted(sessions, key=lambda item: (item.finished_at, item.started_at, item.weapon_used))
    used_ids: set[int] = set()
    next_id = 1

    for session in ordered_sessions:
        current_id = int(session.session_id or 0)

        if current_id > 0 and current_id not in used_ids:
            used_ids.add(current_id)
            next_id = max(next_id, current_id + 1)
            continue

        while next_id in used_ids:
            next_id += 1

        session.session_id = next_id
        used_ids.add(next_id)
        next_id += 1

    return ordered_sessions


def merge_sessions(primary: list[DMResult], fallback: list[DMResult]) -> list[DMResult]:
    merged: list[DMResult] = []
    seen: set[tuple[str, str, int, int, int, int]] = set()

    for session in primary + fallback:
        key = session_identity(session)

        if key in seen:
            continue

        seen.add(key)
        merged.append(session)

    return assign_stable_session_ids(merged)


def load_all_sessions_from_files() -> list[DMResult]:
    csv_sessions = load_sessions_from_csv()
    wallet_sessions = load_sessions_from_wallet_history()

    if csv_sessions:
        return merge_sessions(csv_sessions, wallet_sessions)

    return assign_stable_session_ids(wallet_sessions)


def load_all_sessions() -> list[DMResult]:
    db_sessions = load_local_dm_sessions_from_db()

    if db_sessions:
        return assign_stable_session_ids(db_sessions)

    file_sessions = load_all_sessions_from_files()

    for session in file_sessions:
        upsert_local_dm_session(session)

    return file_sessions


def append_session_to_wallet_history(wallet: dict, result: DMResult | dict[str, Any]) -> dict:
    wallet = normalize_wallet(wallet)
    session_data = result if isinstance(result, DMResult) else DMResult.from_dict(result)
    wallet["sessions"].append(session_data.to_wallet_history_dict())
    return wallet
