from __future__ import annotations

import json
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    sys.modules["requests"] = types.SimpleNamespace()

from core.config import DATA_DIR
from core.tracker_importer import TrackerImportSettings, calculate_fk_fd_from_detail, get_root_data


def validate_fixture() -> None:
    settings = TrackerImportSettings(riot_name="LDN Katsu", riot_tag="LDN")
    payload = {
        "players": [
            {"puuid": "own-puuid", "name": "LDN Katsu", "tag": "LDN"},
            {"puuid": "enemy-puuid", "name": "Enemy", "tag": "ONE"},
        ],
        "kills": [
            {
                "round": 0,
                "time_in_round_in_ms": 9000,
                "killer": {"puuid": "enemy-puuid"},
                "victim": {"puuid": "own-puuid"},
            },
            {
                "round": 0,
                "time_in_round_in_ms": 12000,
                "killer": {"puuid": "own-puuid"},
                "victim": {"puuid": "enemy-puuid"},
            },
            {
                "round": 1,
                "time_in_match_in_ms": 50000,
                "killer_puuid": "own-puuid",
                "victim_puuid": "enemy-puuid",
            },
            {
                "round": 2,
                "kill_time": 1000,
                "killer": {"uuid": "enemy-puuid"},
                "victim": {"uuid": "own-puuid"},
            },
        ],
    }

    fk, fd = calculate_fk_fd_from_detail(payload, settings)
    assert (fk, fd, fk - fd) == (1, 2, -1), (fk, fd, fk - fd)
    print("fixture: FK=1 FD=2 Delta=-1")


def validate_cached_f03() -> None:
    cache_path = DATA_DIR / "tracker_raw" / "ranked_match_detail_f03ca6aa-43b4-4d75-b1d3-c11f4c4d635e.json"
    if not cache_path.exists():
        print("cache f03: arquivo nao encontrado")
        return

    with cache_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    settings = TrackerImportSettings(riot_name="LDN Katsu", riot_tag="LDN")
    fk, fd = calculate_fk_fd_from_detail(get_root_data(payload), settings)
    assert (fk, fd, fk - fd) == (1, 3, -2), (fk, fd, fk - fd)
    print("cache f03: FK=1 FD=3 Delta=-2")


if __name__ == "__main__":
    validate_fixture()
    validate_cached_f03()
