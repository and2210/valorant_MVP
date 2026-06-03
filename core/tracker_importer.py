from __future__ import annotations

import csv
import json
import os
import re
import time
from dataclasses import asdict, dataclass, fields
from datetime import datetime, date
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests

from core.config import DATA_DIR, get_henrik_api_key, load_config, read_env_file
from core.models import to_float, to_int
from core.sqlite_store import (
    finish_import_run,
    load_tracker_dm_payloads_from_db,
    load_tracker_ranked_payloads_from_db,
    replace_tracker_dm_payloads,
    replace_tracker_ranked_payloads,
    save_henrik_raw_payload,
    start_import_run,
)


TRACKER_DM_FILE = DATA_DIR / "tracker_dm_matches.csv"
TRACKER_RAW_DIR = DATA_DIR / "tracker_raw"
API_BASE = "https://api.henrikdev.xyz"
SERVER_ERROR_RETRY_SECONDS = 20
MAX_REQUEST_RETRIES = 5


ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass
class TrackerImportSettings:
    riot_name: str = ""
    riot_tag: str = ""
    region: str = "br"
    platform: str = "pc"
    api_key: str = ""
    import_limit: int = 20
    request_delay_seconds: float = 1.5
    max_scan_matches: int = 500
    batch_size: int = 10
    consecutive_empty_limit: int = 8

    @property
    def is_configured(self) -> bool:
        return bool(self.riot_name and self.riot_tag)


@dataclass
class TrackerDMMatch:
    match_id: str
    date: str
    mode: str
    map_name: str
    agent: str
    placement: str
    score: int
    kills: int
    deaths: int
    assists: int
    kd: float
    acs: float
    adr: float
    hs_percent: float
    headshots: int
    bodyshots: int
    legshots: int
    damage_dealt: int
    damage_received: int
    duration: str
    duration_seconds: int
    linked_session_id: int
    linked_weapon: str
    linked_protocol_rate: float
    linked_clean_hits: int
    linked_valid_attempts: int
    rounds_won: int
    rounds_lost: int
    ally_team: str
    enemy_team: str
    average_rank: str
    average_elo: int
    player_rank: str
    player_elo: int
    raw_queue: str
    raw_mode: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrackerDMMatch":
        return cls(
            match_id=str(data.get("match_id") or ""),
            date=str(data.get("date") or ""),
            mode=str(data.get("mode") or "Deathmatch"),
            map_name=str(data.get("map_name") or ""),
            agent=str(data.get("agent") or ""),
            placement=str(data.get("placement") or ""),
            score=to_int(data.get("score")),
            kills=to_int(data.get("kills")),
            deaths=to_int(data.get("deaths")),
            assists=to_int(data.get("assists")),
            kd=to_float(data.get("kd")),
            acs=to_float(data.get("acs")),
            adr=to_float(data.get("adr")),
            hs_percent=to_float(data.get("hs_percent")),
            headshots=to_int(data.get("headshots")),
            bodyshots=to_int(data.get("bodyshots")),
            legshots=to_int(data.get("legshots")),
            damage_dealt=to_int(data.get("damage_dealt")),
            damage_received=to_int(data.get("damage_received")),
            duration=str(data.get("duration") or ""),
            duration_seconds=to_int(data.get("duration_seconds")),
            linked_session_id=to_int(data.get("linked_session_id")),
            linked_weapon=str(data.get("linked_weapon") or ""),
            linked_protocol_rate=to_float(data.get("linked_protocol_rate")),
            linked_clean_hits=to_int(data.get("linked_clean_hits")),
            linked_valid_attempts=to_int(data.get("linked_valid_attempts")),
            rounds_won=to_int(data.get("rounds_won")),
            rounds_lost=to_int(data.get("rounds_lost")),
            ally_team=str(data.get("ally_team") or ""),
            enemy_team=str(data.get("enemy_team") or ""),
            average_rank=str(data.get("average_rank") or ""),
            average_elo=to_int(data.get("average_elo")),
            player_rank=str(data.get("player_rank") or ""),
            player_elo=to_int(data.get("player_elo")),
            raw_queue=str(data.get("raw_queue") or ""),
            raw_mode=str(data.get("raw_mode") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrackerStats:
    total_matches: int = 0
    average_kd: float = 0.0
    average_hs_percent: float = 0.0
    average_acs: float = 0.0
    average_adr: float = 0.0
    total_kills: int = 0
    total_deaths: int = 0
    total_assists: int = 0
    best_map: str = ""
    best_map_kd: float = 0.0
    best_agent: str = ""
    best_agent_kd: float = 0.0
    average_lobby_elo: float = 0.0
    average_player_elo: float = 0.0
    most_common_lobby_rank: str = ""
    most_common_player_rank: str = ""
    best_match: TrackerDMMatch | None = None
    last_match: TrackerDMMatch | None = None


@dataclass
class TrackerImportResult:
    imported_count: int = 0
    updated_count: int = 0
    skipped_existing_count: int = 0
    scanned_count: int = 0
    deathmatch_found_count: int = 0
    total_saved_count: int = 0
    percent: float = 0.0
    message: str = ""


@dataclass
class TrainingDayStats:
    date: str
    dm_count: int = 0
    total_seconds: int = 0
    total_hours: float = 0.0
    linked_sessions: int = 0
    average_kd: float = 0.0
    average_protocol_rate: float = 0.0
    weapons: str = ""


def get_tracker_settings() -> TrackerImportSettings:
    config = load_config()
    tracker = getattr(config, "tracker", {})

    if not isinstance(tracker, dict):
        tracker = {}

    env_file = read_env_file()

    def value(name: str, default: str = "") -> str:
        return str(tracker.get(name.lower()) or env_file.get(name.upper()) or os.getenv(name.upper(), default) or "").strip()

    return TrackerImportSettings(
        riot_name=str(tracker.get("riot_name") or env_file.get("RIOT_NAME") or os.getenv("RIOT_NAME", "")).strip(),
        riot_tag=str(tracker.get("riot_tag") or env_file.get("RIOT_TAG") or os.getenv("RIOT_TAG", "")).strip(),
        region=str(tracker.get("region") or env_file.get("REGION") or os.getenv("REGION", "br")).strip() or "br",
        platform=str(tracker.get("platform") or env_file.get("PLATFORM") or os.getenv("PLATFORM", "pc")).strip() or "pc",
        api_key=get_henrik_api_key({"tracker": tracker}),
        import_limit=max(to_int(tracker.get("import_limit"), 20), 1),
        request_delay_seconds=max(to_float(tracker.get("request_delay_seconds"), 1.5), 0.0),
        max_scan_matches=max(to_int(tracker.get("max_scan_matches"), 500), 10),
        batch_size=min(max(to_int(tracker.get("batch_size"), 10), 1), 10),
        consecutive_empty_limit=max(to_int(tracker.get("consecutive_empty_limit"), 8), 1),
    )


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_mode(mode: str) -> str:
    value = str(mode or "").lower()
    if "deathmatch" in value or "death" in value:
        return "Deathmatch"
    if "competitive" in value or "ranked" in value:
        return "Competitive"
    return str(mode or "").title()


def calculate_kd(kills: int, deaths: int) -> float:
    if deaths > 0:
        return round(kills / deaths, 2)
    if kills > 0:
        return float(kills)
    return 0.0


def format_duration(value: Any) -> str:
    if value in [None, ""]:
        return ""
    if isinstance(value, dict):
        for key in ["patched", "display", "formatted", "human", "readable"]:
            if value.get(key):
                return str(value.get(key))
        for key in ["seconds", "secs", "milliseconds", "ms"]:
            if value.get(key):
                return format_duration(value.get(key))
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 100000:
            seconds = seconds / 1000
        minutes = int(seconds // 60)
        remaining_seconds = int(seconds % 60)
        return f"{minutes:02d}:{remaining_seconds:02d}"
    return ""


def parse_duration_seconds(value: Any) -> int:
    if value in [None, ""]:
        return 0

    if isinstance(value, dict):
        # Henrik/Valorant APIs podem variar bastante o formato entre versões.
        # Mantemos aliases amplos para evitar calendário zerado.
        for key in [
            "seconds", "secs", "second", "duration_seconds", "duration_in_seconds",
            "game_length_seconds", "length_seconds", "elapsed_seconds",
        ]:
            if value.get(key) not in [None, ""]:
                return max(to_int(value.get(key)), 0)

        for key in [
            "milliseconds", "ms", "millis", "duration_ms", "duration_millis",
            "game_length_in_ms", "game_length_ms", "length_ms", "elapsed_ms",
        ]:
            if value.get(key) not in [None, ""]:
                return max(int(to_float(value.get(key)) / 1000), 0)

        for key in ["patched", "display", "formatted", "human", "readable", "text", "value"]:
            if value.get(key):
                parsed = parse_duration_seconds(value.get(key))
                if parsed > 0:
                    return parsed

    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 100000:
            seconds = seconds / 1000
        return max(int(seconds), 0)

    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return 0

        normalized_number = text.replace(",", ".")
        if normalized_number.replace(".", "", 1).isdigit():
            number = float(normalized_number)
            if number > 100000:
                number = number / 1000
            return max(int(number), 0)

        parts = text.split(":")
        try:
            if len(parts) == 2:
                return int(float(parts[0])) * 60 + int(float(parts[1]))
            if len(parts) == 3:
                return int(float(parts[0])) * 3600 + int(float(parts[1])) * 60 + int(float(parts[2]))
        except ValueError:
            pass

        # Aceita formatos como "7m 35s", "7 min 35 sec", "1h 02m 10s".
        hour_match = re.search(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hora|horas)", text)
        minute_match = re.search(r"(\d+(?:\.\d+)?)\s*(m|min|mins|minuto|minutos)", text)
        second_match = re.search(r"(\d+(?:\.\d+)?)\s*(s|sec|secs|seg|segundo|segundos)", text)
        total = 0.0
        if hour_match:
            total += float(hour_match.group(1)) * 3600
        if minute_match:
            total += float(minute_match.group(1)) * 60
        if second_match:
            total += float(second_match.group(1))
        if total > 0:
            return max(int(total), 0)

    return 0


def format_seconds(seconds: int) -> str:
    seconds = max(int(seconds), 0)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"


def recursive_find_first(data: Any, key_candidates: list[str]) -> Any:
    if isinstance(data, dict):
        for key in key_candidates:
            if key in data and data[key] not in [None, ""]:
                return data[key]
        for value in data.values():
            found = recursive_find_first(value, key_candidates)
            if found not in [None, ""]:
                return found
    elif isinstance(data, list):
        for item in data:
            found = recursive_find_first(item, key_candidates)
            if found not in [None, ""]:
                return found
    return None


def get_nested_name(value: Any) -> str:
    if isinstance(value, dict):
        return clean_text(value.get("name") or value.get("id") or value.get("displayName") or value.get("display_name"))
    return clean_text(value)


def get_match_id(match: dict[str, Any]) -> str:
    metadata = match.get("metadata", {}) if isinstance(match.get("metadata", {}), dict) else {}
    return clean_text(metadata.get("match_id") or metadata.get("matchid") or metadata.get("id") or match.get("match_id"))


def save_raw_match_payload(settings: TrackerImportSettings, raw_match: dict[str, Any], mode: str) -> None:
    try:
        save_henrik_raw_payload(
            endpoint="valorant/v4/matches",
            mode=mode,
            match_id=get_match_id(raw_match),
            riot_name=settings.riot_name,
            riot_tag=settings.riot_tag,
            region=settings.region,
            payload=raw_match,
        )
    except Exception as error:
        print(f"[Raw Henrik] NÃ£o foi possÃ­vel salvar payload bruto: {error}")


def get_map_name(match: dict[str, Any]) -> str:
    metadata = match.get("metadata", {}) if isinstance(match.get("metadata", {}), dict) else {}
    return get_nested_name(metadata.get("map"))


def get_mode_name(match: dict[str, Any]) -> str:
    metadata = match.get("metadata", {}) if isinstance(match.get("metadata", {}), dict) else {}
    queue_info = metadata.get("queue")
    mode_info = metadata.get("mode")
    return get_nested_name(queue_info) or get_nested_name(mode_info)


def get_raw_queue(match: dict[str, Any]) -> str:
    metadata = match.get("metadata", {}) if isinstance(match.get("metadata", {}), dict) else {}
    return get_nested_name(metadata.get("queue"))


def get_raw_mode(match: dict[str, Any]) -> str:
    metadata = match.get("metadata", {}) if isinstance(match.get("metadata", {}), dict) else {}
    return get_nested_name(metadata.get("mode"))


def get_match_date(match: dict[str, Any]) -> str:
    metadata = match.get("metadata", {}) if isinstance(match.get("metadata", {}), dict) else {}
    started_at = metadata.get("started_at")
    if isinstance(started_at, dict):
        for key in ["iso", "full", "date"]:
            value = started_at.get(key)
            if value:
                return str(value)[:19].replace("T", " ")
    if isinstance(started_at, str):
        return started_at[:19].replace("T", " ")
    game_start = metadata.get("game_start") or metadata.get("game_start_unix")
    if isinstance(game_start, (int, float)):
        try:
            if game_start > 10_000_000_000:
                game_start = game_start / 1000
            return datetime.fromtimestamp(game_start).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ""
    return ""


def parse_timestamp_to_datetime(value: Any) -> datetime | None:
    if value in [None, ""]:
        return None

    if isinstance(value, dict):
        for key in ["iso", "full", "date", "patched", "display", "formatted", "value"]:
            parsed = parse_timestamp_to_datetime(value.get(key))
            if parsed is not None:
                return parsed

        for key in ["unix", "timestamp", "seconds", "secs"]:
            parsed = parse_timestamp_to_datetime(value.get(key))
            if parsed is not None:
                return parsed

        for key in ["milliseconds", "ms", "millis"]:
            raw = value.get(key)
            if raw not in [None, ""]:
                return parse_timestamp_to_datetime(to_float(raw) / 1000)

    if isinstance(value, (int, float)):
        try:
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            if timestamp > 0:
                return datetime.fromtimestamp(timestamp)
        except Exception:
            return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.replace(".", "", 1).isdigit():
            return parse_timestamp_to_datetime(float(text))
        candidates = [
            text,
            text[:19].replace("T", " "),
            text.replace("Z", "")[:19].replace("T", " "),
        ]
        for candidate in candidates:
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                try:
                    return datetime.strptime(candidate[:19] if "%S" in fmt else candidate[:10], fmt)
                except ValueError:
                    continue
    return None


def find_match_timestamps(match: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    metadata = match.get("metadata", {}) if isinstance(match.get("metadata", {}), dict) else {}

    start_value = recursive_find_first(metadata, [
        "started_at", "game_start", "game_start_unix", "game_start_patched",
        "start_time", "started", "begin", "begin_at", "created_at",
    ]) or recursive_find_first(match, [
        "started_at", "game_start", "game_start_unix", "game_start_patched",
        "start_time", "started", "begin", "begin_at", "created_at",
    ])

    end_value = recursive_find_first(metadata, [
        "ended_at", "game_end", "game_end_unix", "game_end_patched",
        "end_time", "ended", "finish", "finished_at", "completed_at",
    ]) or recursive_find_first(match, [
        "ended_at", "game_end", "game_end_unix", "game_end_patched",
        "end_time", "ended", "finish", "finished_at", "completed_at",
    ])

    return parse_timestamp_to_datetime(start_value), parse_timestamp_to_datetime(end_value)


DURATION_KEYS = [
    "duration", "duration_seconds", "duration_ms", "duration_millis",
    "game_length", "game_length_in_ms", "game_length_ms", "game_length_seconds",
    "match_length", "match_length_ms", "match_length_seconds",
    "length", "length_ms", "length_seconds",
    "round_length", "elapsed", "elapsed_ms", "elapsed_seconds",
]


def get_match_duration_seconds(match: dict[str, Any]) -> int:
    metadata = match.get("metadata", {}) if isinstance(match.get("metadata", {}), dict) else {}

    for source in [metadata, match]:
        if not isinstance(source, dict):
            continue
        direct_value = recursive_find_first(source, DURATION_KEYS)
        parsed = parse_duration_seconds(direct_value)
        if parsed > 0:
            return parsed

    start_time, end_time = find_match_timestamps(match)
    if start_time is not None and end_time is not None and end_time > start_time:
        return max(int((end_time - start_time).total_seconds()), 0)

    return 0


def get_match_duration(match: dict[str, Any]) -> str:
    seconds = get_match_duration_seconds(match)
    if seconds > 0:
        return format_seconds(seconds)

    metadata = match.get("metadata", {}) if isinstance(match.get("metadata", {}), dict) else {}
    for source in [metadata, match]:
        if not isinstance(source, dict):
            continue
        raw_value = recursive_find_first(source, DURATION_KEYS)
        formatted = format_duration(raw_value)
        if formatted:
            return formatted

    return ""


def flatten_players(match: dict[str, Any]) -> list[dict[str, Any]]:
    players = match.get("players", [])
    if isinstance(players, list):
        return [player for player in players if isinstance(player, dict)]
    if isinstance(players, dict):
        all_players: list[dict[str, Any]] = []
        for value in players.values():
            if isinstance(value, list):
                all_players.extend([player for player in value if isinstance(player, dict)])
            elif isinstance(value, dict):
                nested_players = value.get("players") or value.get("all_players")
                if isinstance(nested_players, list):
                    all_players.extend([player for player in nested_players if isinstance(player, dict)])
        return all_players
    return []


def find_player(match: dict[str, Any], riot_name: str, riot_tag: str) -> dict[str, Any] | None:
    wanted_name = clean_text(riot_name).lower()
    wanted_tag = clean_text(riot_tag).lower()

    for player in flatten_players(match):
        account = player.get("account", {}) if isinstance(player.get("account", {}), dict) else {}
        name = clean_text(
            player.get("name")
            or player.get("game_name")
            or player.get("gameName")
            or player.get("display_name")
            or player.get("displayName")
            or account.get("name")
            or account.get("game_name")
            or account.get("gameName")
            or account.get("display_name")
            or account.get("displayName")
        )
        tag = clean_text(
            player.get("tag")
            or player.get("tag_line")
            or player.get("tagLine")
            or player.get("tagline")
            or account.get("tag")
            or account.get("tag_line")
            or account.get("tagLine")
            or account.get("tagline")
        )

        if wanted_name and wanted_tag and name.lower() == wanted_name and tag.lower() == wanted_tag:
            return player

        riot_id = clean_text(
            player.get("riot_id")
            or player.get("riotId")
            or player.get("display")
            or account.get("riot_id")
            or account.get("riotId")
            or account.get("display")
        ).lower()
        if riot_id and riot_id in {f"{wanted_name}#{wanted_tag}", f"{wanted_name} {wanted_tag}"}:
            return player

    return None


def get_agent_name(player: dict[str, Any]) -> str:
    return get_nested_name(player.get("agent"))


def get_shot_stats(player: dict[str, Any], stats: dict[str, Any]) -> tuple[int, int, int]:
    shots = stats.get("shots", {}) if isinstance(stats.get("shots", {}), dict) else {}
    headshots = to_int(stats.get("headshots") or stats.get("head") or shots.get("head") or shots.get("headshots") or player.get("headshots"))
    bodyshots = to_int(stats.get("bodyshots") or stats.get("body") or shots.get("body") or shots.get("bodyshots") or player.get("bodyshots"))
    legshots = to_int(stats.get("legshots") or stats.get("leg") or shots.get("leg") or shots.get("legshots") or player.get("legshots"))
    return headshots, bodyshots, legshots


def get_damage_stats(player: dict[str, Any], stats: dict[str, Any]) -> tuple[int, int]:
    damage = stats.get("damage", {}) if isinstance(stats.get("damage", {}), dict) else {}
    damage_dealt = to_int(
        stats.get("damage_dealt") or stats.get("damage_made") or stats.get("damage_done") or
        damage.get("dealt") or damage.get("made") or damage.get("done") or
        player.get("damage_dealt") or player.get("damage_made") or player.get("damage_done")
    )
    damage_received = to_int(
        stats.get("damage_received") or stats.get("damage_taken") or damage.get("received") or damage.get("taken") or
        player.get("damage_received") or player.get("damage_taken")
    )
    return damage_dealt, damage_received


def get_team_data(match: dict[str, Any], player: dict[str, Any]) -> dict[str, Any]:
    player_team = clean_text(player.get("team_id") or player.get("team") or player.get("teamId"))
    teams_raw = match.get("teams", [])
    teams: list[dict[str, Any]] = []
    if isinstance(teams_raw, dict):
        for key, value in teams_raw.items():
            if isinstance(value, dict):
                team = dict(value)
                team["_team_key"] = key
                teams.append(team)
    elif isinstance(teams_raw, list):
        teams = [team for team in teams_raw if isinstance(team, dict)]

    ally_team = ""
    enemy_team = ""
    rounds_won = 0
    rounds_lost = 0
    for team in teams:
        team_id = clean_text(team.get("team_id") or team.get("team") or team.get("teamId") or team.get("_team_key"))
        if player_team and team_id and team_id.lower() == player_team.lower():
            ally_team = team_id
            rounds = team.get("rounds", {}) if isinstance(team.get("rounds", {}), dict) else {}
            rounds_won = to_int(team.get("rounds_won") or team.get("roundsWon") or rounds.get("won") or rounds.get("rounds_won"))
            rounds_lost = to_int(team.get("rounds_lost") or team.get("roundsLost") or rounds.get("lost") or rounds.get("rounds_lost"))
            break
    for team in teams:
        team_id = clean_text(team.get("team_id") or team.get("team") or team.get("teamId") or team.get("_team_key"))
        if team_id and ally_team and team_id.lower() != ally_team.lower():
            enemy_team = team_id
            break
    return {"ally_team": ally_team, "enemy_team": enemy_team, "rounds_won": rounds_won, "rounds_lost": rounds_lost}


def get_dm_placement(player: dict[str, Any]) -> str:
    return clean_text(recursive_find_first(player, ["placement", "place", "position", "leaderboard_position", "deathmatch_position"]))


def get_rank_text(data: Any) -> str:
    value = recursive_find_first(
        data,
        [
            "average_rank",
            "average_tier_patched",
            "currenttier_patched",
            "current_tier_patched",
            "tier_patched",
            "rank_patched",
            "rank_name",
            "current_rank",
            "rank",
        ],
    )
    if isinstance(value, dict):
        return clean_text(value.get("name") or value.get("patched") or value.get("id"))
    return clean_text(value)


def get_elo_value(data: Any) -> int:
    value = recursive_find_first(
        data,
        [
            "average_elo",
            "elo",
            "current_elo",
            "tier",
            "currenttier",
            "current_tier",
            "rank_elo",
        ],
    )
    return to_int(value)


def get_average_lobby_rank(match: dict[str, Any]) -> str:
    metadata = match.get("metadata", {}) if isinstance(match.get("metadata", {}), dict) else {}
    return get_rank_text(metadata) or get_rank_text(match.get("teams", {})) or get_rank_text(match)


def get_average_lobby_elo(match: dict[str, Any]) -> int:
    metadata = match.get("metadata", {}) if isinstance(match.get("metadata", {}), dict) else {}
    return get_elo_value(metadata) or get_elo_value(match.get("teams", {})) or get_elo_value(match)


def parse_tracker_dm_match(match: dict[str, Any], settings: TrackerImportSettings) -> TrackerDMMatch | None:
    raw_mode = get_raw_mode(match)
    raw_queue = get_raw_queue(match)
    mode = normalize_mode(get_mode_name(match))
    if mode != "Deathmatch":
        return None

    player = find_player(match, settings.riot_name, settings.riot_tag)
    if player is None:
        return None

    stats = player.get("stats", {}) if isinstance(player.get("stats", {}), dict) else {}
    kills = to_int(player.get("kills") or stats.get("kills"))
    deaths = to_int(player.get("deaths") or stats.get("deaths"))
    assists = to_int(player.get("assists") or stats.get("assists"))
    score = to_int(player.get("score") or stats.get("score"))
    headshots, bodyshots, legshots = get_shot_stats(player, stats)
    total_shots = headshots + bodyshots + legshots
    hs_percent = round((headshots / total_shots) * 100, 2) if total_shots > 0 else 0.0
    damage_dealt, damage_received = get_damage_stats(player, stats)
    team_data = get_team_data(match, player)
    acs = to_float(player.get("acs") or player.get("average_combat_score") or stats.get("acs") or stats.get("average_combat_score"))
    adr = to_float(stats.get("adr") or player.get("adr") or recursive_find_first(player, ["adr", "average_damage_per_round"]))

    player_rank = get_rank_text(player)
    player_elo = get_elo_value(player)

    return TrackerDMMatch(
        match_id=get_match_id(match),
        date=get_match_date(match),
        mode=mode,
        map_name=get_map_name(match),
        agent=get_agent_name(player),
        placement=get_dm_placement(player),
        score=score,
        kills=kills,
        deaths=deaths,
        assists=assists,
        kd=calculate_kd(kills, deaths),
        acs=acs,
        adr=adr,
        hs_percent=hs_percent,
        headshots=headshots,
        bodyshots=bodyshots,
        legshots=legshots,
        damage_dealt=damage_dealt,
        damage_received=damage_received,
        duration=get_match_duration(match),
        duration_seconds=get_match_duration_seconds(match),
        linked_session_id=0,
        linked_weapon="",
        linked_protocol_rate=0.0,
        linked_clean_hits=0,
        linked_valid_attempts=0,
        rounds_won=team_data["rounds_won"],
        rounds_lost=team_data["rounds_lost"],
        ally_team=team_data["ally_team"],
        enemy_team=team_data["enemy_team"],
        average_rank=get_average_lobby_rank(match),
        average_elo=get_average_lobby_elo(match),
        player_rank=player_rank,
        player_elo=player_elo,
        raw_queue=raw_queue,
        raw_mode=raw_mode,
    )


def parse_datetime_safe(value: str) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    candidates = [text, text[:19], text.replace("T", " ")[:19]]
    for candidate in candidates:
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
            try:
                return datetime.strptime(candidate[:19] if fmt.endswith("%S") else candidate[:10], fmt)
            except ValueError:
                continue
    return None


def enrich_tracker_matches_with_local_sessions(matches: list[TrackerDMMatch]) -> list[TrackerDMMatch]:
    """
    Associa DMs reais do Tracker às sessões locais do MVP pelo horário mais próximo.

    A regra é propositalmente simples para o MVP:
    - usa apenas sessões locais do mesmo dia;
    - prefere a sessão finalizada mais próxima do início/fim do DM real;
    - não reutiliza a mesma sessão local em dois DMs;
    - tolerância máxima: 90 minutos.
    """
    try:
        from core.persistence import load_all_sessions
    except Exception:
        return matches

    sessions = load_all_sessions()
    if not sessions or not matches:
        return matches

    session_items = []
    for session in sessions:
        session_time = parse_datetime_safe(session.finished_at) or parse_datetime_safe(session.started_at)
        if session_time is None:
            continue
        session_items.append((session_time, session))

    used_session_ids: set[int] = set()
    for match in sorted(matches, key=lambda item: item.date):
        match_time = parse_datetime_safe(match.date)
        if match_time is None:
            continue

        best_session = None
        best_distance = None
        for session_time, session in session_items:
            if session.session_id in used_session_ids:
                continue
            if session_time.date() != match_time.date():
                continue
            distance = abs((session_time - match_time).total_seconds())
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_session = session

        if best_session is None or best_distance is None or best_distance > 90 * 60:
            continue

        used_session_ids.add(best_session.session_id)
        match.linked_session_id = best_session.session_id
        match.linked_weapon = best_session.weapon_used
        match.linked_protocol_rate = best_session.protocol_rate
        match.linked_clean_hits = best_session.clean_hits
        match.linked_valid_attempts = best_session.valid_attempts
        if match.duration_seconds <= 0 and best_session.duration_seconds > 0:
            match.duration_seconds = best_session.duration_seconds
            match.duration = format_seconds(best_session.duration_seconds)

    return matches


def load_tracker_dm_matches() -> list[TrackerDMMatch]:
    db_payloads = load_tracker_dm_payloads_from_db()

    if db_payloads:
        return enrich_tracker_matches_with_local_sessions([TrackerDMMatch.from_dict(row) for row in db_payloads])

    if not TRACKER_DM_FILE.exists():
        return []

    with TRACKER_DM_FILE.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file, delimiter=";")
        matches = [TrackerDMMatch.from_dict(row) for row in reader if row]
        matches = enrich_tracker_matches_with_local_sessions(matches)
        replace_tracker_dm_payloads([match.to_dict() for match in matches])
        return matches


def save_tracker_dm_matches(matches: list[TrackerDMMatch]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    matches = enrich_tracker_matches_with_local_sessions(matches)
    headers = [field.name for field in fields(TrackerDMMatch)]
    payloads = [match.to_dict() for match in matches]

    with TRACKER_DM_FILE.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=headers, delimiter=";")
        writer.writeheader()
        writer.writerows(payloads)

    replace_tracker_dm_payloads(payloads)


def average(items: list[float]) -> float:
    valid = [item for item in items if item not in [None, ""]]
    if not valid:
        return 0.0
    return round(sum(valid) / len(valid), 2)


def most_common_value(matches: list[TrackerDMMatch], attribute: str) -> str:
    counts: dict[str, int] = {}
    for match in matches:
        value = clean_text(getattr(match, attribute, ""))
        if value:
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda item: item[1])[0]


def best_group_by_kd(matches: list[TrackerDMMatch], attribute: str) -> tuple[str, float]:
    groups: dict[str, list[TrackerDMMatch]] = {}
    for match in matches:
        key = clean_text(getattr(match, attribute, ""))
        if key:
            groups.setdefault(key, []).append(match)
    best_name = ""
    best_kd = 0.0
    for name, items in groups.items():
        kd = round(sum(item.kd for item in items) / len(items), 2)
        if kd > best_kd:
            best_name = name
            best_kd = kd
    return best_name, best_kd


def build_tracker_stats(matches: list[TrackerDMMatch] | None = None) -> TrackerStats:
    matches = matches if matches is not None else load_tracker_dm_matches()
    stats = TrackerStats(total_matches=len(matches))
    if not matches:
        return stats

    sorted_matches = sorted(matches, key=lambda item: item.date, reverse=True)
    stats.last_match = sorted_matches[0]
    stats.best_match = max(matches, key=lambda item: (item.kills, item.kd, item.score))
    stats.total_kills = sum(match.kills for match in matches)
    stats.total_deaths = sum(match.deaths for match in matches)
    stats.total_assists = sum(match.assists for match in matches)
    stats.average_kd = calculate_kd(stats.total_kills, stats.total_deaths)
    stats.average_hs_percent = average([match.hs_percent for match in matches])
    stats.average_acs = average([match.acs for match in matches])
    stats.average_adr = average([match.adr for match in matches])
    stats.average_lobby_elo = average([match.average_elo for match in matches if match.average_elo > 0])
    stats.average_player_elo = average([match.player_elo for match in matches if match.player_elo > 0])
    stats.most_common_lobby_rank = most_common_value(matches, "average_rank")
    stats.most_common_player_rank = most_common_value(matches, "player_rank")
    stats.best_map, stats.best_map_kd = best_group_by_kd(matches, "map_name")
    stats.best_agent, stats.best_agent_kd = best_group_by_kd(matches, "agent")
    return stats


def build_training_calendar(matches: list[TrackerDMMatch] | None = None) -> list[TrainingDayStats]:
    matches = matches if matches is not None else load_tracker_dm_matches()
    grouped: dict[str, list[TrackerDMMatch]] = {}
    for match in matches:
        day = clean_text(match.date)[:10]
        if not day:
            continue
        grouped.setdefault(day, []).append(match)

    result: list[TrainingDayStats] = []
    for day, day_matches in grouped.items():
        total_seconds = sum(match.duration_seconds for match in day_matches)
        total_kills = sum(match.kills for match in day_matches)
        total_deaths = sum(match.deaths for match in day_matches)
        linked = [match for match in day_matches if match.linked_session_id > 0]
        protocol_values = [match.linked_protocol_rate for match in linked if match.linked_valid_attempts > 0]
        weapons = sorted({match.linked_weapon for match in linked if match.linked_weapon})
        avg_protocol = round(sum(protocol_values) / len(protocol_values), 1) if protocol_values else 0.0
        result.append(TrainingDayStats(
            date=day,
            dm_count=len(day_matches),
            total_seconds=total_seconds,
            total_hours=round(total_seconds / 3600, 2) if total_seconds > 0 else 0.0,
            linked_sessions=len(linked),
            average_kd=calculate_kd(total_kills, total_deaths),
            average_protocol_rate=avg_protocol,
            weapons=", ".join(weapons),
        ))

    return sorted(result, key=lambda item: item.date, reverse=True)


def build_match_url(settings: TrackerImportSettings, start: int, size: int) -> str:
    name_encoded = quote(settings.riot_name, safe="")
    tag_encoded = quote(settings.riot_tag, safe="")
    return (
        f"{API_BASE}/valorant/v4/matches/"
        f"{settings.region}/{settings.platform}/{name_encoded}/{tag_encoded}"
        f"?size={size}&start={start}"
    )


def get_retry_after_seconds(response: requests.Response) -> int:
    retry_after = response.headers.get("Retry-After") or response.headers.get("x-ratelimit-reset")
    if retry_after:
        try:
            return max(int(float(retry_after)) + 5, 1)
        except ValueError:
            pass
    return 180


def request_matches(settings: TrackerImportSettings, start: int, size: int) -> list[dict[str, Any]]:
    headers = {"Accept": "application/json", "User-Agent": "mvp-kcred-tracker-importer/0.3"}
    if settings.api_key:
        headers["Authorization"] = settings.api_key

    url = build_match_url(settings, start, size)
    last_detail = ""

    for attempt in range(1, MAX_REQUEST_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, timeout=35)
        except requests.RequestException as error:
            last_detail = str(error)
            wait_seconds = min(SERVER_ERROR_RETRY_SECONDS * attempt, 90)
            print(f"[Tracker] Falha de conexão na tentativa {attempt}/{MAX_REQUEST_RETRIES}: {error}")
            if attempt < MAX_REQUEST_RETRIES:
                print(f"[Tracker] Aguardando {wait_seconds}s antes de tentar novamente...")
                time.sleep(wait_seconds)
                continue
            raise RuntimeError(f"Falha de conexão com Henrik API: {error}")

        if response.status_code == 200:
            payload = response.json()
            TRACKER_RAW_DIR.mkdir(parents=True, exist_ok=True)
            raw_path = TRACKER_RAW_DIR / f"matches_start_{start}_size_{size}.json"
            with raw_path.open("w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2, ensure_ascii=False)
            data = payload.get("data", []) if isinstance(payload, dict) else []
            return data if isinstance(data, list) else []

        try:
            payload = response.json()
            last_detail = json.dumps(payload, ensure_ascii=False)[:700]
        except Exception:
            last_detail = response.text[:700]

        if response.status_code == 429:
            wait_seconds = get_retry_after_seconds(response)
            print(f"[Tracker] Rate limit detectado ({attempt}/{MAX_REQUEST_RETRIES}). Aguardando {wait_seconds}s...")
            if attempt < MAX_REQUEST_RETRIES:
                time.sleep(wait_seconds)
                continue

        if 500 <= response.status_code <= 599:
            wait_seconds = min(SERVER_ERROR_RETRY_SECONDS * attempt, 90)
            print(
                f"[Tracker] Erro temporário Henrik HTTP {response.status_code} "
                f"({attempt}/{MAX_REQUEST_RETRIES}). Aguardando {wait_seconds}s..."
            )
            if attempt < MAX_REQUEST_RETRIES:
                time.sleep(wait_seconds)
                continue

        raise RuntimeError(f"Henrik API retornou HTTP {response.status_code}: {last_detail}")

    raise RuntimeError(f"Henrik API não respondeu após {MAX_REQUEST_RETRIES} tentativas: {last_detail}")




def build_mmr_history_url(settings: TrackerImportSettings) -> str:
    name_encoded = quote(settings.riot_name, safe="")
    tag_encoded = quote(settings.riot_tag, safe="")
    return (
        f"{API_BASE}/valorant/v2/mmr-history/"
        f"{settings.region}/{settings.platform}/{name_encoded}/{tag_encoded}"
    )


def build_match_detail_url(settings: TrackerImportSettings, match_id: str) -> str:
    return f"{API_BASE}/valorant/v4/match/{settings.region}/{match_id}"


def request_json_url(
    settings: TrackerImportSettings,
    url: str,
    raw_filename: str | None = None,
    label: str = "Tracker",
) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "mvp-kcred-tracker-importer/0.4"}
    if settings.api_key:
        headers["Authorization"] = settings.api_key

    last_detail = ""
    for attempt in range(1, MAX_REQUEST_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, timeout=35)
        except requests.RequestException as error:
            last_detail = str(error)
            wait_seconds = min(SERVER_ERROR_RETRY_SECONDS * attempt, 90)
            print(f"[{label}] Falha de conexão na tentativa {attempt}/{MAX_REQUEST_RETRIES}: {error}")
            if attempt < MAX_REQUEST_RETRIES:
                print(f"[{label}] Aguardando {wait_seconds}s antes de tentar novamente...")
                time.sleep(wait_seconds)
                continue
            raise RuntimeError(f"Falha de conexão com Henrik API: {error}")

        try:
            payload = response.json()
        except Exception:
            payload = {}

        if response.status_code == 200:
            if raw_filename:
                TRACKER_RAW_DIR.mkdir(parents=True, exist_ok=True)
                raw_path = TRACKER_RAW_DIR / raw_filename
                with raw_path.open("w", encoding="utf-8") as file:
                    json.dump(payload, file, indent=2, ensure_ascii=False)
            return payload if isinstance(payload, dict) else {}

        if isinstance(payload, dict):
            last_detail = json.dumps(payload, ensure_ascii=False)[:700]
        else:
            last_detail = response.text[:700]

        if response.status_code == 429:
            wait_seconds = get_retry_after_seconds(response)
            print(f"[{label}] Rate limit detectado ({attempt}/{MAX_REQUEST_RETRIES}). Aguardando {wait_seconds}s...")
            if attempt < MAX_REQUEST_RETRIES:
                time.sleep(wait_seconds)
                continue

        if 500 <= response.status_code <= 599:
            wait_seconds = min(SERVER_ERROR_RETRY_SECONDS * attempt, 90)
            print(
                f"[{label}] Erro temporário Henrik HTTP {response.status_code} "
                f"({attempt}/{MAX_REQUEST_RETRIES}). Aguardando {wait_seconds}s..."
            )
            if attempt < MAX_REQUEST_RETRIES:
                time.sleep(wait_seconds)
                continue

        raise RuntimeError(f"Henrik API retornou HTTP {response.status_code}: {last_detail}")

    raise RuntimeError(f"Henrik API não respondeu após {MAX_REQUEST_RETRIES} tentativas: {last_detail}")


def fetch_mmr_history_payload(settings: TrackerImportSettings) -> dict[str, Any]:
    url = build_mmr_history_url(settings)
    print("=" * 80)
    print("ENRIQUECIMENTO RANKED — MMR HISTORY")
    print(url)
    return request_json_url(settings, url, raw_filename="ranked_mmr_history.json", label="MMR")


def build_mmr_by_match_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    history: list[Any] = []

    if isinstance(data, dict):
        raw_history = data.get("history", [])
        if isinstance(raw_history, list):
            history = raw_history
    elif isinstance(data, list):
        history = data

    result: dict[str, dict[str, Any]] = {}
    for item in history:
        if not isinstance(item, dict):
            continue
        match_id = clean_text(item.get("match_id"))
        if not match_id:
            continue

        tier = item.get("tier", {})
        rank_name = ""
        if isinstance(tier, dict):
            rank_name = clean_text(tier.get("name") or tier.get("patched") or tier.get("displayName"))
        else:
            rank_name = clean_text(tier)

        result[match_id] = {
            "rank": rank_name,
            "rr": to_int(item.get("rr")),
            "rr_change": to_int(item.get("last_change")),
            "elo": to_int(item.get("elo")),
            "date": clean_text(item.get("date")),
        }

    print(f"[MMR] Partidas ranked disponíveis para enriquecimento: {len(result)}")
    return result


def get_cached_match_detail(settings: TrackerImportSettings, match_id: str) -> dict[str, Any]:
    if not match_id:
        return {}

    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", match_id)
    raw_path = TRACKER_RAW_DIR / f"ranked_match_detail_{safe_id}.json"

    if raw_path.exists():
        try:
            with raw_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
            if isinstance(payload, dict):
                try:
                    save_henrik_raw_payload(
                        endpoint="valorant/v4/match",
                        mode="ranked_detail",
                        match_id=match_id,
                        riot_name=settings.riot_name,
                        riot_tag=settings.riot_tag,
                        region=settings.region,
                        payload=payload,
                    )
                except Exception:
                    pass
                return payload
        except Exception:
            pass

    url = build_match_detail_url(settings, match_id)
    payload = request_json_url(settings, url, raw_filename=f"ranked_match_detail_{safe_id}.json", label="Ranked detalhe")
    try:
        save_henrik_raw_payload(
            endpoint="valorant/v4/match",
            mode="ranked_detail",
            match_id=match_id,
            riot_name=settings.riot_name,
            riot_tag=settings.riot_tag,
            region=settings.region,
            payload=payload,
        )
    except Exception as error:
        print(f"[Raw Henrik] NÃ£o foi possÃ­vel salvar detalhe bruto: {error}")
    if settings.request_delay_seconds > 0:
        time.sleep(settings.request_delay_seconds)
    return payload


def get_root_data(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def get_player_identifiers(player: dict[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    candidate_keys = ["puuid", "uuid", "id", "player_id", "account_id", "subject"]

    for key in candidate_keys:
        value = player.get(key)
        if value:
            identifiers.add(clean_text(value).lower())

    account = player.get("account", {}) if isinstance(player.get("account", {}), dict) else {}
    for key in candidate_keys:
        value = account.get(key)
        if value:
            identifiers.add(clean_text(value).lower())

    name = clean_text(
        player.get("name")
        or player.get("game_name")
        or player.get("gameName")
        or player.get("display_name")
        or player.get("displayName")
        or account.get("name")
        or account.get("game_name")
        or account.get("gameName")
        or account.get("display_name")
        or account.get("displayName")
    )
    tag = clean_text(
        player.get("tag")
        or player.get("tag_line")
        or player.get("tagLine")
        or player.get("tagline")
        or account.get("tag")
        or account.get("tag_line")
        or account.get("tagLine")
        or account.get("tagline")
    )
    if name:
        identifiers.add(name.lower())
    if name and tag:
        identifiers.add(f"{name.lower()}#{tag.lower()}")
        identifiers.add(f"{name.lower()} {tag.lower()}")

    riot_id = clean_text(
        player.get("riot_id")
        or player.get("riotId")
        or player.get("display")
        or account.get("riot_id")
        or account.get("riotId")
        or account.get("display")
    )
    if riot_id:
        identifiers.add(riot_id.lower())

    return identifiers


def extract_identifier_from_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return clean_text(value).lower()
    if isinstance(value, dict):
        candidate_keys = ["puuid", "uuid", "id", "player_id", "account_id", "subject"]
        for key in candidate_keys:
            if value.get(key):
                return clean_text(value.get(key)).lower()
        account = value.get("account", {}) if isinstance(value.get("account", {}), dict) else {}
        for key in candidate_keys:
            if account.get(key):
                return clean_text(account.get(key)).lower()
        name = clean_text(
            value.get("name")
            or value.get("game_name")
            or value.get("gameName")
            or value.get("display_name")
            or value.get("displayName")
            or account.get("name")
            or account.get("game_name")
            or account.get("gameName")
            or account.get("display_name")
            or account.get("displayName")
        )
        tag = clean_text(
            value.get("tag")
            or value.get("tag_line")
            or value.get("tagLine")
            or value.get("tagline")
            or account.get("tag")
            or account.get("tag_line")
            or account.get("tagLine")
            or account.get("tagline")
        )
        if name and tag:
            return f"{name.lower()}#{tag.lower()}"
        if name:
            return name.lower()
    return ""


def get_event_actor_id(event: dict[str, Any], role: str) -> str:
    if role == "killer":
        keys = [
            "killer", "killer_puuid", "killer_uuid", "killer_id", "killerId",
            "killerPuuid", "killerSubject", "killer_subject", "killer_account",
            "killerAccount", "killer_name", "killerName", "killer_display_name",
            "killerDisplayName", "killer_displayName", "killerGameName", "killer_game_name",
        ]
    elif role == "victim":
        keys = [
            "victim", "victim_puuid", "victim_uuid", "victim_id", "victimId",
            "victimPuuid", "victimSubject", "victim_subject", "victim_account",
            "victimAccount", "victim_name", "victimName", "victim_display_name",
            "victimDisplayName", "victim_displayName", "victimGameName", "victim_game_name",
        ]
    else:
        return ""

    for key in keys:
        if key in event:
            actor_id = extract_identifier_from_value(event.get(key))
            if actor_id:
                return actor_id
    return ""


def get_event_time(event: dict[str, Any]) -> int:
    keys = [
        "time_in_round_in_ms", "timeInRoundInMs",
        "kill_time_in_round", "killTimeInRound",
        "kill_time", "killTime",
        "time_in_match_in_ms", "timeInMatchInMs",
        "time_since_round_start_millis", "timeSinceRoundStartMillis",
        "time_since_round_start_in_ms", "timeSinceRoundStartInMs",
        "time_since_round_start_ms", "timeSinceRoundStartMs",
        "round_time", "roundTime", "round_time_millis", "roundTimeMillis",
        "round_time_in_ms", "roundTimeInMs", "round_time_ms", "roundTimeMs",
        "time", "timestamp", "game_time", "gameTime",
        "game_time_in_ms", "gameTimeInMs", "game_time_ms", "gameTimeMs",
        "time_since_game_start_millis", "timeSinceGameStartMillis",
        "time_since_game_start_in_ms", "timeSinceGameStartInMs",
    ]
    for key in keys:
        if key in event:
            return to_int(event.get(key))
    return 0


def get_kill_event_round(event: dict[str, Any]) -> str:
    keys = [
        "round", "round_id", "roundId", "round_number", "roundNumber",
        "round_index", "roundIndex",
    ]
    for key in keys:
        if key in event and event.get(key) not in [None, ""]:
            return clean_text(event.get(key))
    return ""


def looks_like_kill_event(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    keys = {str(key).lower() for key in item.keys()}
    return any("killer" in key for key in keys) and any("victim" in key for key in keys)


def collect_kill_events(data: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if isinstance(data, dict):
        if looks_like_kill_event(data):
            events.append(data)
        for value in data.values():
            events.extend(collect_kill_events(value))
    elif isinstance(data, list):
        for item in data:
            events.extend(collect_kill_events(item))
    return events


def extract_round_groups(match_data: dict[str, Any]) -> list[list[Any]]:
    candidates: list[list[Any]] = []

    def walk(data: Any) -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, list) and "round" in str(key).lower() and any(isinstance(item, dict) for item in value):
                    candidates.append(value)
                walk(value)
        elif isinstance(data, list):
            for item in data:
                walk(item)

    walk(match_data)
    candidates.sort(key=len, reverse=True)
    return candidates


def calculate_fk_fd_from_kills_list(kills: list[Any], own_identifiers: set[str]) -> tuple[int, int]:
    kills_by_round: dict[str, list[dict[str, Any]]] = {}

    for event in kills:
        if not isinstance(event, dict):
            continue

        round_key = get_kill_event_round(event)
        if not round_key:
            continue

        killer_id = get_event_actor_id(event, "killer")
        victim_id = get_event_actor_id(event, "victim")
        if not killer_id or not victim_id:
            continue

        kills_by_round.setdefault(round_key, []).append({
            "killer_id": killer_id,
            "victim_id": victim_id,
            "time": get_event_time(event),
        })

    fk = 0
    fd = 0
    for round_kills in kills_by_round.values():
        if not round_kills:
            continue

        round_kills.sort(key=lambda item: item["time"])
        first_event = round_kills[0]
        if first_event["killer_id"] in own_identifiers:
            fk += 1
        if first_event["victim_id"] in own_identifiers:
            fd += 1

    return fk, fd


def calculate_fk_fd_from_detail(match_data: dict[str, Any], settings: TrackerImportSettings) -> tuple[int, int]:
    own_player = find_player(match_data, settings.riot_name, settings.riot_tag)
    if own_player is None:
        return 0, 0

    own_identifiers = get_player_identifiers(own_player)
    wanted_name = clean_text(settings.riot_name).lower()
    wanted_tag = clean_text(settings.riot_tag).lower()
    if wanted_name:
        own_identifiers.add(wanted_name)
    if wanted_name and wanted_tag:
        own_identifiers.add(f"{wanted_name}#{wanted_tag}")
        own_identifiers.add(f"{wanted_name} {wanted_tag}")
    if not own_identifiers:
        return 0, 0

    # Alguns payloads da Henrik já trazem first_kills/first_deaths por jogador
    # dentro de rounds/stats. Este caminho é mais barato e evita depender do
    # formato exato dos eventos de kill.
    direct_fk = to_int(
        recursive_find_first(own_player, ["first_kills", "first_kill", "first_bloods", "first_blood"])
    )
    direct_fd = to_int(
        recursive_find_first(own_player, ["first_deaths", "first_death"])
    )
    if direct_fk or direct_fd:
        return direct_fk, direct_fd

    kills = match_data.get("kills")
    if isinstance(kills, list):
        fk, fd = calculate_fk_fd_from_kills_list(kills, own_identifiers)
        if fk or fd:
            return fk, fd

    round_groups = extract_round_groups(match_data)
    if not round_groups:
        return 0, 0

    fk = 0
    fd = 0
    rounds = round_groups[0]

    for round_data in rounds:
        if not isinstance(round_data, dict):
            continue

        kill_events = collect_kill_events(round_data)
        normalized: list[dict[str, Any]] = []
        seen_events: set[tuple[str, str, int]] = set()

        for event in kill_events:
            killer_id = get_event_actor_id(event, "killer")
            victim_id = get_event_actor_id(event, "victim")
            if not killer_id or not victim_id:
                continue

            event_time = get_event_time(event)
            event_key = (killer_id, victim_id, event_time)
            if event_key in seen_events:
                continue
            seen_events.add(event_key)

            normalized.append({
                "killer_id": killer_id,
                "victim_id": victim_id,
                "time": event_time,
            })

        if not normalized:
            continue

        normalized.sort(key=lambda item: item["time"])
        first_event = normalized[0]
        if first_event["killer_id"] in own_identifiers:
            fk += 1
        if first_event["victim_id"] in own_identifiers:
            fd += 1

    return fk, fd


def enrich_ranked_match(
    match: TrackerRankedMatch,
    settings: TrackerImportSettings,
    mmr_by_match_id: dict[str, dict[str, Any]],
) -> TrackerRankedMatch:
    mmr = mmr_by_match_id.get(match.match_id, {}) if match.match_id else {}
    if mmr:
        if mmr.get("rank"):
            match.rank = clean_text(mmr.get("rank"))
        if mmr.get("rr") not in [None, ""]:
            match.rr = to_int(mmr.get("rr"))
        if mmr.get("rr_change") not in [None, ""]:
            match.rr_change = to_int(mmr.get("rr_change"))
        if mmr.get("elo") not in [None, ""]:
            match.elo = to_int(mmr.get("elo"))

    config = load_config()
    tracker_config = config.tracker if isinstance(config.tracker, dict) else {}
    detail_enabled = bool(tracker_config.get("ranked_detail_enrichment", True))
    detail_limit_enabled = match.match_id and detail_enabled and match.first_kills == 0 and match.first_deaths == 0

    if detail_limit_enabled:
        try:
            payload = get_cached_match_detail(settings, match.match_id)
            detail = get_root_data(payload)
            fk, fd = calculate_fk_fd_from_detail(detail, settings)
            if fk or fd:
                match.first_kills = fk
                match.first_deaths = fd
                match.fb_fd_delta = fk - fd
        except Exception as error:
            print(f"[Ranked detalhe] Não foi possível enriquecer FK/FD de {match.match_id}: {error}")

    return match

def emit_progress(callback: ProgressCallback | None, **payload: Any) -> None:
    if callback is not None:
        callback(payload)



def get_match_day_key(value: str) -> str:
    text = clean_text(value)
    if len(text) >= 10:
        return text[:10]
    return ""


def normalize_date_filter(value: str | date | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = clean_text(value)
    if len(text) >= 10:
        return text[:10]
    return ""


def date_in_range(day_key: str, start_date: str, end_date: str) -> bool:
    if not day_key:
        return False
    if start_date and day_key < start_date:
        return False
    if end_date and day_key > end_date:
        return False
    return True


def remove_matches_in_date_range(matches: list[TrackerDMMatch], start_date: str, end_date: str) -> list[TrackerDMMatch]:
    if not start_date and not end_date:
        return matches

    kept = []
    for match in matches:
        day_key = get_match_day_key(match.date)
        if date_in_range(day_key, start_date, end_date):
            continue
        kept.append(match)
    return kept


def import_deathmatch_from_tracker(
    limit: int | None = None,
    import_all: bool = False,
    progress_callback: ProgressCallback | None = None,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    replace_date_range: bool = False,
) -> TrackerImportResult:
    settings = get_tracker_settings()
    if not settings.is_configured:
        return TrackerImportResult(message="Tracker não configurado. Preencha .env ou data/config.json com RIOT_NAME e RIOT_TAG.")

    filter_start = normalize_date_filter(start_date)
    filter_end = normalize_date_filter(end_date)
    has_date_filter = bool(filter_start or filter_end)
    run_id = start_import_run(import_type="deathmatch", requested_start=filter_start, requested_end=filter_end)

    max_scan = settings.max_scan_matches if (import_all or has_date_filter) else max(int(limit or settings.import_limit) * 6, 40)
    max_scan = max(max_scan, settings.batch_size)
    target_new = None if (import_all or has_date_filter) else max(int(limit or settings.import_limit), 1)

    existing = load_tracker_dm_matches()
    if replace_date_range and has_date_filter:
        existing = remove_matches_in_date_range(existing, filter_start, filter_end)
    matches_by_id = {match.match_id: match for match in existing if match.match_id}
    imported_count = 0
    updated_count = 0
    scanned_count = 0
    deathmatch_found_count = 0
    start = 0
    consecutive_empty_batches = 0

    print("=" * 80)
    print("IMPORTAÇÃO TRACKER / HENRIK — DEATHMATCH")
    print(f"Riot ID: {settings.riot_name}#{settings.riot_tag}")
    print(f"Região/plataforma: {settings.region}/{settings.platform}")
    if has_date_filter:
        print(f"Modo: atualização por data ({filter_start or 'início'} até {filter_end or 'hoje'})")
    else:
        print(f"Modo: {'todos os DMs dentro do limite de varredura' if import_all else f'{target_new} DMs novos'}")
    print(f"Limite de varredura: {max_scan} partidas")
    print("=" * 80)

    while scanned_count < max_scan:
        remaining_scan = max_scan - scanned_count
        batch_size = min(settings.batch_size, remaining_scan)
        try:
            batch = request_matches(settings, start=start, size=batch_size)
        except Exception as error:
            finish_import_run(
                run_id,
                status="failed",
                total_found=deathmatch_found_count,
                total_inserted=imported_count,
                total_updated=updated_count,
                total_skipped=max(deathmatch_found_count - imported_count - updated_count, 0),
                scanned_count=scanned_count,
                error_message=str(error),
            )
            raise
        if not batch:
            break

        scanned_count += len(batch)
        found_before = deathmatch_found_count

        for raw_match in batch:
            if not isinstance(raw_match, dict):
                continue
            save_raw_match_payload(settings, raw_match, "deathmatch")
            parsed = parse_tracker_dm_match(raw_match, settings)
            if parsed is None:
                continue

            parsed_day = get_match_day_key(parsed.date)
            if has_date_filter and not date_in_range(parsed_day, filter_start, filter_end):
                # A API retorna partidas em ordem decrescente na maioria dos casos.
                # Ao passar da data inicial, podemos encerrar a varredura do período.
                if filter_start and parsed_day and parsed_day < filter_start:
                    scanned_count = max_scan
                    break
                continue

            deathmatch_found_count += 1
            if parsed.match_id and parsed.match_id in matches_by_id:
                # Atualiza dados antigos caso o schema novo tenha mais campos.
                matches_by_id[parsed.match_id] = parsed
                updated_count += 1
                continue

            if parsed.match_id:
                matches_by_id[parsed.match_id] = parsed
            else:
                synthetic_id = f"no-id-{parsed.date}-{parsed.map_name}-{parsed.kills}-{parsed.deaths}-{parsed.score}"
                parsed.match_id = synthetic_id
                matches_by_id[synthetic_id] = parsed
            imported_count += 1

            if target_new is not None and imported_count >= target_new:
                break

        if deathmatch_found_count == found_before:
            consecutive_empty_batches += 1
        else:
            consecutive_empty_batches = 0

        percent = round(min((scanned_count / max_scan) * 100, 100), 1)
        print(
            f"[Tracker] {percent:5.1f}% | escaneadas {scanned_count}/{max_scan} | "
            f"DMs encontrados {deathmatch_found_count} | novos {imported_count} | atualizados {updated_count}"
        )
        emit_progress(
            progress_callback,
            percent=percent,
            scanned_count=scanned_count,
            max_scan=max_scan,
            deathmatch_found_count=deathmatch_found_count,
            imported_count=imported_count,
            updated_count=updated_count,
        )

        if target_new is not None and imported_count >= target_new:
            break
        if consecutive_empty_batches >= settings.consecutive_empty_limit:
            print("[Tracker] Parando: muitos lotes seguidos sem Deathmatch encontrado.")
            break

        start += len(batch)
        if settings.request_delay_seconds > 0 and scanned_count < max_scan:
            time.sleep(settings.request_delay_seconds)

    all_matches = sorted(matches_by_id.values(), key=lambda item: item.date, reverse=True)
    try:
        save_tracker_dm_matches(all_matches)
    except Exception as error:
        finish_import_run(
            run_id,
            status="failed",
            total_found=deathmatch_found_count,
            total_inserted=imported_count,
            total_updated=updated_count,
            total_skipped=max(deathmatch_found_count - imported_count - updated_count, 0),
            scanned_count=scanned_count,
            error_message=str(error),
        )
        raise
    percent = round(min((scanned_count / max_scan) * 100, 100), 1)
    finish_import_run(
        run_id,
        status="success",
        total_found=deathmatch_found_count,
        total_inserted=imported_count,
        total_updated=updated_count,
        total_skipped=max(deathmatch_found_count - imported_count - updated_count, 0),
        scanned_count=scanned_count,
        message=f"DM import: {imported_count} inserted, {updated_count} updated",
    )

    return TrackerImportResult(
        imported_count=imported_count,
        updated_count=updated_count,
        skipped_existing_count=max(deathmatch_found_count - imported_count, 0),
        scanned_count=scanned_count,
        deathmatch_found_count=deathmatch_found_count,
        total_saved_count=len(all_matches),
        percent=percent,
        message=(
            f"Importação concluída: {imported_count} DMs novos, "
            f"{updated_count} atualizados, {len(all_matches)} DMs salvos."
        ),
    )

# =============================================================================
# RADIANTE — RANKED / COMPETITIVE IMPORT
# =============================================================================

TRACKER_RANKED_FILE = DATA_DIR / "tracker_ranked_matches.csv"


@dataclass
class TrackerRankedMatch:
    match_id: str
    date: str
    mode: str
    map_name: str
    agent: str
    result: str
    rank: str
    rr: int
    rr_change: int
    elo: int
    kills: int
    deaths: int
    assists: int
    kd: float
    acs: float
    adr: float
    kast: float
    hs_percent: float
    headshots: int
    bodyshots: int
    legshots: int
    damage_dealt: int
    damage_received: int
    damage_delta: int
    dd_per_round: float
    first_kills: int
    first_deaths: int
    fb_fd_delta: int
    rounds_won: int
    rounds_lost: int
    duration: str
    duration_seconds: int
    ally_team: str
    enemy_team: str
    average_rank: str
    average_elo: int
    raw_queue: str
    raw_mode: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrackerRankedMatch":
        return cls(
            match_id=str(data.get("match_id") or ""),
            date=str(data.get("date") or ""),
            mode=str(data.get("mode") or "Competitive"),
            map_name=str(data.get("map_name") or ""),
            agent=str(data.get("agent") or ""),
            result=str(data.get("result") or ""),
            rank=str(data.get("rank") or ""),
            rr=to_int(data.get("rr")),
            rr_change=to_int(data.get("rr_change")),
            elo=to_int(data.get("elo")),
            kills=to_int(data.get("kills")),
            deaths=to_int(data.get("deaths")),
            assists=to_int(data.get("assists")),
            kd=to_float(data.get("kd")),
            acs=to_float(data.get("acs")),
            adr=to_float(data.get("adr")),
            kast=to_float(data.get("kast")),
            hs_percent=to_float(data.get("hs_percent")),
            headshots=to_int(data.get("headshots")),
            bodyshots=to_int(data.get("bodyshots")),
            legshots=to_int(data.get("legshots")),
            damage_dealt=to_int(data.get("damage_dealt")),
            damage_received=to_int(data.get("damage_received")),
            damage_delta=to_int(data.get("damage_delta")),
            dd_per_round=to_float(data.get("dd_per_round")),
            first_kills=to_int(data.get("first_kills")),
            first_deaths=to_int(data.get("first_deaths")),
            fb_fd_delta=to_int(data.get("fb_fd_delta")),
            rounds_won=to_int(data.get("rounds_won")),
            rounds_lost=to_int(data.get("rounds_lost")),
            duration=str(data.get("duration") or ""),
            duration_seconds=to_int(data.get("duration_seconds")),
            ally_team=str(data.get("ally_team") or ""),
            enemy_team=str(data.get("enemy_team") or ""),
            average_rank=str(data.get("average_rank") or ""),
            average_elo=to_int(data.get("average_elo")),
            raw_queue=str(data.get("raw_queue") or ""),
            raw_mode=str(data.get("raw_mode") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RankedRadianteStats:
    total_matches: int = 0
    wins: int = 0
    losses: int = 0
    winrate: float = 0.0
    average_acs: float = 0.0
    average_adr: float = 0.0
    average_kast: float = 0.0
    average_hs_percent: float = 0.0
    kd: float = 0.0
    total_rr_change: int = 0
    average_rr_change: float = 0.0
    total_damage_delta: int = 0
    average_damage_delta: float = 0.0
    average_dd_per_round: float = 0.0
    total_first_kills: int = 0
    total_first_deaths: int = 0
    fb_fd_delta: int = 0
    best_map: str = ""
    best_map_winrate: float = 0.0
    worst_map: str = ""
    worst_map_winrate: float = 0.0
    dominant_signal: str = ""
    next_focus: str = ""
    last_match: TrackerRankedMatch | None = None


def get_result_from_team(match: dict[str, Any], player: dict[str, Any]) -> str:
    player_team = clean_text(player.get("team_id") or player.get("team") or player.get("teamId"))
    teams_raw = match.get("teams", [])
    teams: list[dict[str, Any]] = []
    if isinstance(teams_raw, dict):
        for key, value in teams_raw.items():
            if isinstance(value, dict):
                team = dict(value)
                team["_team_key"] = key
                teams.append(team)
    elif isinstance(teams_raw, list):
        teams = [team for team in teams_raw if isinstance(team, dict)]

    for team in teams:
        team_id = clean_text(team.get("team_id") or team.get("team") or team.get("teamId") or team.get("_team_key"))
        if player_team and team_id and team_id.lower() == player_team.lower():
            won = team.get("won")
            if won is True:
                return "Win"
            if won is False:
                return "Loss"
            result = clean_text(team.get("result") or team.get("outcome"))
            if result:
                return result.title()
    return ""


def get_optional_float_stat(player: dict[str, Any], stats: dict[str, Any], keys: list[str]) -> float:
    for key in keys:
        if key in stats and stats.get(key) not in [None, ""]:
            return to_float(stats.get(key))
        if key in player and player.get(key) not in [None, ""]:
            return to_float(player.get(key))
    found = recursive_find_first(player, keys)
    return to_float(found)


def get_first_blood_stats(player: dict[str, Any], stats: dict[str, Any]) -> tuple[int, int, int]:
    first_kills = to_int(
        stats.get("first_kills") or stats.get("first_kill") or stats.get("first_bloods") or stats.get("first_blood") or
        player.get("first_kills") or player.get("first_kill") or player.get("first_bloods") or player.get("first_blood") or
        recursive_find_first(player, ["first_kills", "first_kill", "first_bloods", "first_blood"])
    )
    first_deaths = to_int(
        stats.get("first_deaths") or stats.get("first_death") or player.get("first_deaths") or player.get("first_death") or
        recursive_find_first(player, ["first_deaths", "first_death"])
    )
    return first_kills, first_deaths, first_kills - first_deaths


def get_ranked_mmr_fields(match: dict[str, Any], player: dict[str, Any]) -> tuple[str, int, int, int]:
    rank = get_rank_text(player) or get_rank_text(match)
    rr = to_int(recursive_find_first(player, ["rr", "ranking_in_tier", "ranked_rating", "current_rr"]))
    rr_change = to_int(recursive_find_first(player, ["rr_change", "last_change", "mmr_change", "ranked_rating_change"]))
    elo = get_elo_value(player) or get_elo_value(match)
    return rank, rr, rr_change, elo


def parse_tracker_ranked_match(match: dict[str, Any], settings: TrackerImportSettings) -> TrackerRankedMatch | None:
    raw_mode = get_raw_mode(match)
    raw_queue = get_raw_queue(match)
    mode = normalize_mode(get_mode_name(match))
    if mode != "Competitive":
        return None

    player = find_player(match, settings.riot_name, settings.riot_tag)
    if player is None:
        return None

    stats = player.get("stats", {}) if isinstance(player.get("stats", {}), dict) else {}
    kills = to_int(player.get("kills") or stats.get("kills"))
    deaths = to_int(player.get("deaths") or stats.get("deaths"))
    assists = to_int(player.get("assists") or stats.get("assists"))
    headshots, bodyshots, legshots = get_shot_stats(player, stats)
    total_shots = headshots + bodyshots + legshots
    hs_percent = round((headshots / total_shots) * 100, 2) if total_shots > 0 else 0.0
    damage_dealt, damage_received = get_damage_stats(player, stats)
    damage_delta = damage_dealt - damage_received
    team_data = get_team_data(match, player)
    total_rounds = to_int(team_data["rounds_won"]) + to_int(team_data["rounds_lost"])
    dd_per_round = round(damage_delta / total_rounds, 2) if total_rounds > 0 else 0.0
    score = to_int(player.get("score") or stats.get("score"))
    acs = to_float(
        player.get("acs") or player.get("average_combat_score") or
        stats.get("acs") or stats.get("average_combat_score") or
        recursive_find_first(player, ["acs", "average_combat_score", "combat_score"])
    )
    if acs <= 0 and total_rounds > 0 and score > 0:
        acs = round(score / total_rounds, 2)

    adr = get_optional_float_stat(player, stats, ["adr", "average_damage_per_round"])
    if adr <= 0 and total_rounds > 0 and damage_dealt > 0:
        adr = round(damage_dealt / total_rounds, 2)

    kast = get_optional_float_stat(player, stats, ["kast", "kast_percent", "kast_percentage"])
    first_kills, first_deaths, fb_fd_delta = get_first_blood_stats(player, stats)
    if first_kills == 0 and first_deaths == 0:
        try:
            calculated_fk, calculated_fd = calculate_fk_fd_from_detail(match, settings)
            if calculated_fk or calculated_fd:
                first_kills = calculated_fk
                first_deaths = calculated_fd
                fb_fd_delta = calculated_fk - calculated_fd
        except Exception:
            pass

    rank, rr, rr_change, elo = get_ranked_mmr_fields(match, player)

    return TrackerRankedMatch(
        match_id=get_match_id(match),
        date=get_match_date(match),
        mode=mode,
        map_name=get_map_name(match),
        agent=get_agent_name(player),
        result=get_result_from_team(match, player),
        rank=rank,
        rr=rr,
        rr_change=rr_change,
        elo=elo,
        kills=kills,
        deaths=deaths,
        assists=assists,
        kd=calculate_kd(kills, deaths),
        acs=acs,
        adr=adr,
        kast=kast,
        hs_percent=hs_percent,
        headshots=headshots,
        bodyshots=bodyshots,
        legshots=legshots,
        damage_dealt=damage_dealt,
        damage_received=damage_received,
        damage_delta=damage_delta,
        dd_per_round=dd_per_round,
        first_kills=first_kills,
        first_deaths=first_deaths,
        fb_fd_delta=fb_fd_delta,
        rounds_won=team_data["rounds_won"],
        rounds_lost=team_data["rounds_lost"],
        duration=get_match_duration(match),
        duration_seconds=get_match_duration_seconds(match),
        ally_team=team_data["ally_team"],
        enemy_team=team_data["enemy_team"],
        average_rank=get_average_lobby_rank(match),
        average_elo=get_average_lobby_elo(match),
        raw_queue=raw_queue,
        raw_mode=raw_mode,
    )


def load_tracker_ranked_matches() -> list[TrackerRankedMatch]:
    db_payloads = load_tracker_ranked_payloads_from_db()

    if db_payloads:
        return [TrackerRankedMatch.from_dict(row) for row in db_payloads]

    if not TRACKER_RANKED_FILE.exists():
        return []

    with TRACKER_RANKED_FILE.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file, delimiter=";")
        matches = [TrackerRankedMatch.from_dict(row) for row in reader if row]
        replace_tracker_ranked_payloads([match.to_dict() for match in matches])
        return matches


def save_tracker_ranked_matches(matches: list[TrackerRankedMatch]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    headers = [field.name for field in fields(TrackerRankedMatch)]
    payloads = [match.to_dict() for match in matches]

    with TRACKER_RANKED_FILE.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=headers, delimiter=";")
        writer.writeheader()
        writer.writerows(payloads)

    replace_tracker_ranked_payloads(payloads)


def build_ranked_radiante_stats(matches: list[TrackerRankedMatch] | None = None, last_n: int = 20) -> RankedRadianteStats:
    all_matches = matches if matches is not None else load_tracker_ranked_matches()
    matches = sorted(all_matches, key=lambda item: item.date, reverse=True)[:last_n]
    stats = RankedRadianteStats(total_matches=len(matches))
    if not matches:
        return stats

    stats.last_match = matches[0]
    stats.wins = len([match for match in matches if match.result.lower() == "win"])
    stats.losses = len([match for match in matches if match.result.lower() == "loss"])
    decided = stats.wins + stats.losses
    stats.winrate = round((stats.wins / decided) * 100, 1) if decided > 0 else 0.0
    total_kills = sum(match.kills for match in matches)
    total_deaths = sum(match.deaths for match in matches)
    stats.kd = calculate_kd(total_kills, total_deaths)
    stats.average_acs = average([match.acs for match in matches if match.acs > 0])
    stats.average_adr = average([match.adr for match in matches if match.adr > 0])
    stats.average_kast = average([match.kast for match in matches if match.kast > 0])
    stats.average_hs_percent = average([match.hs_percent for match in matches if match.hs_percent > 0])
    stats.total_rr_change = sum(match.rr_change for match in matches)
    rr_values = [match.rr_change for match in matches if match.rr_change != 0]
    stats.average_rr_change = average([float(value) for value in rr_values])
    stats.total_damage_delta = sum(match.damage_delta for match in matches)
    stats.average_damage_delta = average([float(match.damage_delta) for match in matches])
    stats.average_dd_per_round = average([match.dd_per_round for match in matches if match.dd_per_round != 0])
    stats.total_first_kills = sum(match.first_kills for match in matches)
    stats.total_first_deaths = sum(match.first_deaths for match in matches)
    stats.fb_fd_delta = stats.total_first_kills - stats.total_first_deaths

    # Winrate por mapa para sinal competitivo simples.
    map_groups: dict[str, list[TrackerRankedMatch]] = {}
    for match in matches:
        if match.map_name:
            map_groups.setdefault(match.map_name, []).append(match)
    map_rates = []
    for map_name, items in map_groups.items():
        wins = len([item for item in items if item.result.lower() == "win"])
        losses = len([item for item in items if item.result.lower() == "loss"])
        total = wins + losses
        if total > 0:
            map_rates.append((map_name, round((wins / total) * 100, 1), total))
    if map_rates:
        stats.best_map, stats.best_map_winrate, _ = max(map_rates, key=lambda item: (item[1], item[2]))
        stats.worst_map, stats.worst_map_winrate, _ = min(map_rates, key=lambda item: (item[1], -item[2]))

    if stats.fb_fd_delta < -5:
        stats.dominant_signal = "FD acima do FB"
        stats.next_focus = "Reduzir primeiras mortes: não contestar primeiro contato sem vantagem/utilidade."
    elif stats.average_dd_per_round < -5:
        stats.dominant_signal = "DDΔ negativo"
        stats.next_focus = "Trocar dano de forma mais saudável: sobreviver após causar dano e jogar com trade."
    elif stats.average_acs < 190:
        stats.dominant_signal = "Impacto baixo"
        stats.next_focus = "Aumentar presença útil por round: usar utilidade para gerar contato favorável."
    elif stats.winrate < 50:
        stats.dominant_signal = "Winrate abaixo de 50%"
        stats.next_focus = "Revisar decisões de round: transformar vantagem individual em round ganho."
    else:
        stats.dominant_signal = "Base competitiva estável"
        stats.next_focus = "Manter consistência e procurar padrão específico por mapa/lado."

    return stats


def import_ranked_from_tracker(
    limit: int | None = None,
    import_all: bool = False,
    progress_callback: ProgressCallback | None = None,
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    replace_date_range: bool = False,
) -> TrackerImportResult:
    settings = get_tracker_settings()
    if not settings.is_configured:
        return TrackerImportResult(message="Tracker não configurado. Preencha .env ou data/config.json com RIOT_NAME e RIOT_TAG.")

    filter_start = normalize_date_filter(start_date)
    filter_end = normalize_date_filter(end_date)
    has_date_filter = bool(filter_start or filter_end)
    run_id = start_import_run(import_type="ranked", requested_start=filter_start, requested_end=filter_end)

    max_scan = settings.max_scan_matches if (import_all or has_date_filter) else max(int(limit or settings.import_limit) * 8, 60)
    max_scan = max(max_scan, settings.batch_size)
    target_new = None if (import_all or has_date_filter) else max(int(limit or settings.import_limit), 1)

    mmr_by_match_id: dict[str, dict[str, Any]] = {}
    try:
        mmr_by_match_id = build_mmr_by_match_id(fetch_mmr_history_payload(settings))
        if settings.request_delay_seconds > 0:
            time.sleep(settings.request_delay_seconds)
    except Exception as error:
        print(f"[MMR] Enriquecimento indisponível. A importação continuará sem Rank/RR: {error}")

    existing = load_tracker_ranked_matches()
    if replace_date_range and has_date_filter:
        existing = [match for match in existing if not date_in_range(get_match_day_key(match.date), filter_start, filter_end)]
    matches_by_id = {match.match_id: match for match in existing if match.match_id}
    imported_count = 0
    updated_count = 0
    scanned_count = 0
    ranked_found_count = 0
    start = 0
    consecutive_empty_batches = 0

    print("=" * 80)
    print("IMPORTAÇÃO TRACKER / HENRIK — RANKED / COMPETITIVE")
    print(f"Riot ID: {settings.riot_name}#{settings.riot_tag}")
    print(f"Região/plataforma: {settings.region}/{settings.platform}")
    print(f"Limite de varredura: {max_scan} partidas")
    print("=" * 80)

    while scanned_count < max_scan:
        remaining_scan = max_scan - scanned_count
        batch_size = min(settings.batch_size, remaining_scan)
        try:
            batch = request_matches(settings, start=start, size=batch_size)
        except Exception as error:
            finish_import_run(
                run_id,
                status="failed",
                total_found=ranked_found_count,
                total_inserted=imported_count,
                total_updated=updated_count,
                total_skipped=max(ranked_found_count - imported_count - updated_count, 0),
                scanned_count=scanned_count,
                error_message=str(error),
            )
            raise
        if not batch:
            break

        scanned_count += len(batch)
        found_before = ranked_found_count

        for raw_match in batch:
            if not isinstance(raw_match, dict):
                continue
            save_raw_match_payload(settings, raw_match, "ranked")
            parsed = parse_tracker_ranked_match(raw_match, settings)
            if parsed is None:
                continue

            parsed = enrich_ranked_match(parsed, settings, mmr_by_match_id)

            parsed_day = get_match_day_key(parsed.date)
            if has_date_filter and not date_in_range(parsed_day, filter_start, filter_end):
                if filter_start and parsed_day and parsed_day < filter_start:
                    scanned_count = max_scan
                    break
                continue

            ranked_found_count += 1
            if parsed.match_id and parsed.match_id in matches_by_id:
                matches_by_id[parsed.match_id] = parsed
                updated_count += 1
                continue

            if parsed.match_id:
                matches_by_id[parsed.match_id] = parsed
            else:
                synthetic_id = f"ranked-no-id-{parsed.date}-{parsed.map_name}-{parsed.kills}-{parsed.deaths}"
                parsed.match_id = synthetic_id
                matches_by_id[synthetic_id] = parsed
            imported_count += 1

            if target_new is not None and imported_count >= target_new:
                break

        if ranked_found_count == found_before:
            consecutive_empty_batches += 1
        else:
            consecutive_empty_batches = 0

        percent = round(min((scanned_count / max_scan) * 100, 100), 1)
        print(
            f"[Ranked] {percent:5.1f}% | escaneadas {scanned_count}/{max_scan} | "
            f"rankeds encontradas {ranked_found_count} | novas {imported_count} | atualizadas {updated_count}"
        )
        emit_progress(
            progress_callback,
            percent=percent,
            scanned_count=scanned_count,
            max_scan=max_scan,
            ranked_found_count=ranked_found_count,
            imported_count=imported_count,
            updated_count=updated_count,
        )

        if target_new is not None and imported_count >= target_new:
            break
        if consecutive_empty_batches >= settings.consecutive_empty_limit:
            print("[Ranked] Parando: muitos lotes seguidos sem ranked encontrada.")
            break

        start += len(batch)
        if settings.request_delay_seconds > 0 and scanned_count < max_scan:
            time.sleep(settings.request_delay_seconds)

    all_matches = sorted(matches_by_id.values(), key=lambda item: item.date, reverse=True)
    try:
        save_tracker_ranked_matches(all_matches)
    except Exception as error:
        finish_import_run(
            run_id,
            status="failed",
            total_found=ranked_found_count,
            total_inserted=imported_count,
            total_updated=updated_count,
            total_skipped=max(ranked_found_count - imported_count - updated_count, 0),
            scanned_count=scanned_count,
            error_message=str(error),
        )
        raise
    percent = round(min((scanned_count / max_scan) * 100, 100), 1)
    finish_import_run(
        run_id,
        status="success",
        total_found=ranked_found_count,
        total_inserted=imported_count,
        total_updated=updated_count,
        total_skipped=max(ranked_found_count - imported_count - updated_count, 0),
        scanned_count=scanned_count,
        message=f"Ranked import: {imported_count} inserted, {updated_count} updated",
    )

    return TrackerImportResult(
        imported_count=imported_count,
        updated_count=updated_count,
        skipped_existing_count=max(ranked_found_count - imported_count, 0),
        scanned_count=scanned_count,
        deathmatch_found_count=ranked_found_count,
        total_saved_count=len(all_matches),
        percent=percent,
        message=(
            f"Importação concluída: {imported_count} rankeds novas, "
            f"{updated_count} atualizadas, {len(all_matches)} rankeds salvas."
        ),
    )
