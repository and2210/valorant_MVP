from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def get_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = get_project_root()
DATA_DIR = PROJECT_ROOT / "data"

WALLET_FILE = DATA_DIR / "wallet.json"
SESSIONS_FILE = DATA_DIR / "sessions.csv"
INVENTORY_FILE = DATA_DIR / "inventory.json"
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_WEAPONS = {
    "0": {"name": "Classic", "cost": 0},
    "1": {"name": "Ghost", "cost": 500},
    "2": {"name": "Bandit", "cost": 600},
    "3": {"name": "Sheriff", "cost": 800},
    "4": {"name": "Bulldog", "cost": 2050},
    "5": {"name": "Guardian", "cost": 2250},
    "6": {"name": "Phantom", "cost": 2900},
    "7": {"name": "Vandal", "cost": 2900},
    "8": {"name": "Operator", "cost": 4700},
}

MOVEMENT_KEYS = {"w", "a", "s", "d"}
LATERAL_KEYS = {"a", "d"}
FORWARD_KEYS = {"w", "s"}

# Mantidos para compatibilidade com imports antigos.
EPISODE_TIMEOUT = 1.25
POST_CLICK_COOLDOWN = 0.25
REQUIRE_RELEASE_AT_CLICK = False
KCRED_PER_CLEAN_HIT = 10
KCRED_PENALTY_BRAKE_ERROR = 5
KCRED_PENALTY_DIAGONAL_ERROR = 5
KCRED_PENALTY_NO_AD_ERROR = 5
STATIONARY_CLICK_COUNTS_CLEAN = True
STATIONARY_MIN_RELEASE_SECONDS = 0.10
XP_PER_CLEAN_HIT = 2
XP_PER_LEVEL = 5000
DEFAULT_STARTING_BALANCE = 0
DEFAULT_NEXT_WEAPON = "Classic"
WEAPONS = DEFAULT_WEAPONS


@dataclass
class AppConfig:
    episode_timeout: float = EPISODE_TIMEOUT
    post_click_cooldown: float = POST_CLICK_COOLDOWN
    require_release_at_click: bool = REQUIRE_RELEASE_AT_CLICK
    kcred_per_clean_hit: int = KCRED_PER_CLEAN_HIT
    kcred_penalty_brake_error: int = KCRED_PENALTY_BRAKE_ERROR
    kcred_penalty_diagonal_error: int = KCRED_PENALTY_DIAGONAL_ERROR
    kcred_penalty_no_ad_error: int = KCRED_PENALTY_NO_AD_ERROR
    stationary_click_counts_clean: bool = STATIONARY_CLICK_COUNTS_CLEAN
    stationary_min_release_seconds: float = STATIONARY_MIN_RELEASE_SECONDS
    xp_per_clean_hit: int = XP_PER_CLEAN_HIT
    xp_per_level: int = XP_PER_LEVEL
    default_starting_balance: int = DEFAULT_STARTING_BALANCE
    default_next_weapon: str = DEFAULT_NEXT_WEAPON
    weapons: dict[str, dict[str, Any]] = field(default_factory=lambda: dict(DEFAULT_WEAPONS))
    tracker: dict[str, Any] = field(default_factory=lambda: {
        "riot_name": "",
        "riot_tag": "",
        "region": "br",
        "platform": "pc",
        "api_key": "",
        "import_limit": 20,
        "request_delay_seconds": 1.5,
        "max_scan_matches": 2500,
        "batch_size": 10,
        "consecutive_empty_limit": 8,
        "ranked_detail_enrichment": True,
    })
    training_calendar: dict[str, Any] = field(default_factory=lambda: {
        "daily_goal_hours": 2.0,
        "light_day_hours": 0.5,
        "medium_day_hours": 1.0,
        "strong_day_hours": 2.0,
        "export_filename": "training_calendar_month.csv",
    })
    session_automation: dict[str, Any] = field(default_factory=lambda: {
        "auto_arm_enabled": False,
    })
    protocol: dict[str, Any] = field(default_factory=lambda: {
        "diagonal_footwork_rule_deathmatch": "strict_footwork",
        "diagonal_footwork_rule_ranked": "informational",
        "shot_linked_window_seconds": 0.50,
        "debug_event_limit": 12,
    })
    input_timing: dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "tap_max_seconds": 0.12,
        "burst_max_seconds": 0.50,
        "crouch_fire_max_seconds": 0.50,
        "action_map": {
            "w": "forward",
            "a": "left",
            "s": "backward",
            "d": "right",
            "q": "ability_q",
            "e": "ability_e",
            "c": "ability_c",
            "x": "ultimate",
            "z": "ability_z",
            "v": "ability_v",
            "r": "reload",
            "f": "interact",
            "space": "jump",
            "scroll_up": "scroll_jump",
            "scroll_down": "scroll_down",
            "ctrl": "crouch",
            "shift": "walk",
            "tab": "scoreboard",
            "grave": "grave",
            "mouse_left": "fire",
            "mouse_right": "alt_fire",
            "mouse_middle": "mouse_middle",
            "mouse_x1": "spray",
            "mouse_x2": "mouse_extra",
        },
    })

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        defaults = cls()
        weapons = data.get("weapons", defaults.weapons)

        if not isinstance(weapons, dict) or not weapons:
            weapons = defaults.weapons

        normalized_weapons: dict[str, dict[str, Any]] = {}

        for key, weapon in weapons.items():
            if not isinstance(weapon, dict):
                continue

            name = str(weapon.get("name") or "").strip()

            if not name:
                continue

            try:
                cost = int(weapon.get("cost", 0))
            except (TypeError, ValueError):
                cost = 0

            normalized_weapons[str(key)] = {"name": name, "cost": max(cost, 0)}

        if not normalized_weapons:
            normalized_weapons = defaults.weapons

        tracker = data.get("tracker", defaults.tracker)
        if not isinstance(tracker, dict):
            tracker = defaults.tracker

        normalized_tracker = dict(defaults.tracker)
        normalized_tracker.update(tracker)
        normalized_tracker["riot_name"] = str(normalized_tracker.get("riot_name") or "").strip()
        normalized_tracker["riot_tag"] = str(normalized_tracker.get("riot_tag") or "").strip()
        normalized_tracker["region"] = str(normalized_tracker.get("region") or "br").strip() or "br"
        normalized_tracker["platform"] = str(normalized_tracker.get("platform") or "pc").strip() or "pc"
        normalized_tracker["api_key"] = str(normalized_tracker.get("api_key") or "").strip()
        normalized_tracker["import_limit"] = max(_to_int(normalized_tracker.get("import_limit"), 20), 1)
        normalized_tracker["request_delay_seconds"] = max(_to_float(normalized_tracker.get("request_delay_seconds"), 1.5), 0.0)
        normalized_tracker["max_scan_matches"] = max(_to_int(normalized_tracker.get("max_scan_matches"), 2500), 10)
        normalized_tracker["batch_size"] = min(max(_to_int(normalized_tracker.get("batch_size"), 10), 1), 10)
        normalized_tracker["consecutive_empty_limit"] = max(_to_int(normalized_tracker.get("consecutive_empty_limit"), 8), 1)
        normalized_tracker["ranked_detail_enrichment"] = bool(normalized_tracker.get("ranked_detail_enrichment", True))

        training_calendar = data.get("training_calendar", defaults.training_calendar)
        if not isinstance(training_calendar, dict):
            training_calendar = defaults.training_calendar

        normalized_training_calendar = dict(defaults.training_calendar)
        normalized_training_calendar.update(training_calendar)
        normalized_training_calendar["daily_goal_hours"] = max(_to_float(normalized_training_calendar.get("daily_goal_hours"), 2.0), 0.1)
        normalized_training_calendar["light_day_hours"] = max(_to_float(normalized_training_calendar.get("light_day_hours"), 0.5), 0.1)
        normalized_training_calendar["medium_day_hours"] = max(_to_float(normalized_training_calendar.get("medium_day_hours"), 1.0), 0.1)
        normalized_training_calendar["strong_day_hours"] = max(_to_float(normalized_training_calendar.get("strong_day_hours"), 2.0), 0.1)
        normalized_training_calendar["export_filename"] = str(normalized_training_calendar.get("export_filename") or "training_calendar_month.csv").strip()

        session_automation = data.get("session_automation", defaults.session_automation)
        if not isinstance(session_automation, dict):
            session_automation = defaults.session_automation

        normalized_session_automation = dict(defaults.session_automation)
        normalized_session_automation.update(session_automation)
        normalized_session_automation["auto_arm_enabled"] = bool(
            normalized_session_automation.get("auto_arm_enabled", False)
        )

        protocol = data.get("protocol", defaults.protocol)
        if not isinstance(protocol, dict):
            protocol = defaults.protocol

        normalized_protocol = dict(defaults.protocol)
        normalized_protocol.update(protocol)
        valid_diagonal_modes = {"strict_footwork", "shot_linked", "informational", "disabled"}
        deathmatch_mode = str(normalized_protocol.get("diagonal_footwork_rule_deathmatch") or "strict_footwork").strip()
        ranked_mode = str(normalized_protocol.get("diagonal_footwork_rule_ranked") or "informational").strip()
        normalized_protocol["diagonal_footwork_rule_deathmatch"] = (
            deathmatch_mode if deathmatch_mode in valid_diagonal_modes else "strict_footwork"
        )
        normalized_protocol["diagonal_footwork_rule_ranked"] = (
            ranked_mode if ranked_mode in valid_diagonal_modes else "informational"
        )
        normalized_protocol["shot_linked_window_seconds"] = max(
            _to_float(normalized_protocol.get("shot_linked_window_seconds"), 0.50),
            0.05,
        )
        normalized_protocol["debug_event_limit"] = max(
            _to_int(normalized_protocol.get("debug_event_limit"), 12),
            1,
        )

        input_timing = data.get("input_timing", defaults.input_timing)
        if not isinstance(input_timing, dict):
            input_timing = defaults.input_timing

        normalized_input_timing = dict(defaults.input_timing)
        normalized_input_timing.update(input_timing)
        normalized_input_timing["enabled"] = bool(normalized_input_timing.get("enabled", True))
        normalized_input_timing["tap_max_seconds"] = max(_to_float(normalized_input_timing.get("tap_max_seconds"), 0.12), 0.01)
        normalized_input_timing["burst_max_seconds"] = max(_to_float(normalized_input_timing.get("burst_max_seconds"), 0.50), 0.05)
        normalized_input_timing["crouch_fire_max_seconds"] = max(_to_float(normalized_input_timing.get("crouch_fire_max_seconds"), 0.50), 0.05)

        action_map = normalized_input_timing.get("action_map")
        if not isinstance(action_map, dict):
            action_map = defaults.input_timing["action_map"]

        normalized_action_map: dict[str, str] = {}
        for key, value in action_map.items():
            key_text = str(key or "").strip()
            value_text = str(value or "").strip()
            if key_text and value_text:
                normalized_action_map[key_text] = value_text

        if not normalized_action_map:
            normalized_action_map = dict(defaults.input_timing["action_map"])

        normalized_input_timing["action_map"] = normalized_action_map

        return cls(
            episode_timeout=_to_float(data.get("episode_timeout"), defaults.episode_timeout),
            post_click_cooldown=_to_float(data.get("post_click_cooldown"), defaults.post_click_cooldown),
            require_release_at_click=bool(data.get("require_release_at_click", defaults.require_release_at_click)),
            kcred_per_clean_hit=max(_to_int(data.get("kcred_per_clean_hit"), defaults.kcred_per_clean_hit), 0),
            kcred_penalty_brake_error=max(_to_int(data.get("kcred_penalty_brake_error"), defaults.kcred_penalty_brake_error), 0),
            kcred_penalty_diagonal_error=max(_to_int(data.get("kcred_penalty_diagonal_error"), defaults.kcred_penalty_diagonal_error), 0),
            kcred_penalty_no_ad_error=max(_to_int(data.get("kcred_penalty_no_ad_error"), defaults.kcred_penalty_no_ad_error), 0),
            stationary_click_counts_clean=bool(data.get("stationary_click_counts_clean", defaults.stationary_click_counts_clean)),
            stationary_min_release_seconds=max(_to_float(data.get("stationary_min_release_seconds"), defaults.stationary_min_release_seconds), 0.0),
            xp_per_clean_hit=max(_to_int(data.get("xp_per_clean_hit"), defaults.xp_per_clean_hit), 0),
            xp_per_level=max(_to_int(data.get("xp_per_level"), defaults.xp_per_level), 1),
            default_starting_balance=_to_int(data.get("default_starting_balance"), defaults.default_starting_balance),
            default_next_weapon=str(data.get("default_next_weapon") or defaults.default_next_weapon),
            weapons=normalized_weapons,
            tracker=normalized_tracker,
            training_calendar=normalized_training_calendar,
            session_automation=normalized_session_automation,
            protocol=normalized_protocol,
            input_timing=normalized_input_timing,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def default_config_dict() -> dict[str, Any]:
    return AppConfig().to_dict()


def load_config() -> AppConfig:
    ensure_data_dir()

    if not CONFIG_FILE.exists():
        config = AppConfig()
        save_config(config)
        return config

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except json.JSONDecodeError:
        config = AppConfig()
        save_config(config)
        return config

    if not isinstance(raw_data, dict):
        config = AppConfig()
        save_config(config)
        return config

    config = AppConfig.from_dict(raw_data)

    # Regrava com campos novos caso o arquivo seja de uma versão antiga.
    save_config(config)
    return config


def save_config(config: AppConfig) -> None:
    ensure_data_dir()

    with CONFIG_FILE.open("w", encoding="utf-8") as file:
        json.dump(config.to_dict(), file, ensure_ascii=False, indent=4)
