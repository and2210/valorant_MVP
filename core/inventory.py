from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import DEFAULT_NEXT_WEAPON, INVENTORY_FILE, WALLET_FILE, load_config
from core.kcred_engine import buy_weapon as buy_weapon_with_kcred
from core.kcred_engine import can_buy_weapon
from core.models import DATETIME_FORMAT
from core.persistence import load_wallet, save_wallet
from core.sqlite_store import load_inventory_from_db, save_inventory_to_db


DEFAULT_OWNED_WEAPONS = [DEFAULT_NEXT_WEAPON]
WEAPON_GROUPS: dict[str, list[str]] = {
    "Sidearms": ["Classic", "Shorty", "Frenzy", "Ghost", "Sheriff", "Bandit"],
    "SMGs / Shotguns": ["Stinger", "Spectre", "Bucky", "Judge"],
    "Rifles": ["Bulldog", "Guardian", "Phantom", "Vandal"],
    "Snipers / Heavies": ["Marshal", "Outlaw", "Operator", "Ares", "Odin"],
}


def _ensure_data_dir() -> None:
    INVENTORY_FILE.parent.mkdir(parents=True, exist_ok=True)


def get_weapons() -> dict[str, dict[str, Any]]:
    return load_config().weapons


def get_default_weapon_name() -> str:
    config = load_config()
    default_name = config.default_next_weapon

    if get_weapon_by_name(default_name) is None:
        return DEFAULT_NEXT_WEAPON

    return default_name


def default_inventory() -> dict[str, Any]:
    default_weapon = get_default_weapon_name()

    return {
        "next_weapon": default_weapon,
        "owned_weapons": [default_weapon],
        "purchase_history": [],
        "weapon_usage": {},
        "version": 1,
    }


def normalize_inventory(inventory: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(inventory, dict):
        inventory = default_inventory()

    default_weapon = get_default_weapon_name()
    next_weapon = str(inventory.get("next_weapon") or default_weapon).strip()

    if get_weapon_by_name(next_weapon) is None:
        next_weapon = default_weapon

    owned_weapons = inventory.get("owned_weapons", [])

    if not isinstance(owned_weapons, list):
        owned_weapons = []

    normalized_owned = []

    for weapon_name in owned_weapons:
        weapon_name = str(weapon_name or "").strip()

        if weapon_name and get_weapon_by_name(weapon_name) is not None and weapon_name not in normalized_owned:
            normalized_owned.append(weapon_name)

    if next_weapon not in normalized_owned:
        normalized_owned.append(next_weapon)

    if default_weapon not in normalized_owned:
        normalized_owned.insert(0, default_weapon)

    purchase_history = inventory.get("purchase_history", [])

    if not isinstance(purchase_history, list):
        purchase_history = []

    normalized_purchase_history = [
        item for item in purchase_history
        if isinstance(item, dict)
    ]

    weapon_usage = inventory.get("weapon_usage", {})

    if not isinstance(weapon_usage, dict):
        weapon_usage = {}

    normalized_usage = {}

    for weapon_name, count in weapon_usage.items():
        weapon_name = str(weapon_name or "").strip()

        if not weapon_name or get_weapon_by_name(weapon_name) is None:
            continue

        try:
            normalized_usage[weapon_name] = max(int(count), 0)
        except (TypeError, ValueError):
            normalized_usage[weapon_name] = 0

    return {
        "next_weapon": next_weapon,
        "owned_weapons": normalized_owned,
        "purchase_history": normalized_purchase_history,
        "weapon_usage": normalized_usage,
        "version": int(inventory.get("version", 1) or 1),
    }


def load_inventory() -> dict[str, Any]:
    _ensure_data_dir()

    db_inventory = load_inventory_from_db()

    if db_inventory is not None:
        return normalize_inventory(db_inventory)

    if not INVENTORY_FILE.exists():
        inventory = default_inventory()

        # Migração suave da v0.4: se a carteira antiga já tinha próxima arma,
        # ela vira o estado inicial do inventário separado.
        if WALLET_FILE.exists():
            try:
                with WALLET_FILE.open("r", encoding="utf-8") as file:
                    wallet_data = json.load(file)

                wallet_next_weapon = str(wallet_data.get("next_weapon") or "").strip()

                if wallet_next_weapon and get_weapon_by_name(wallet_next_weapon) is not None:
                    inventory["next_weapon"] = wallet_next_weapon

                    if wallet_next_weapon not in inventory["owned_weapons"]:
                        inventory["owned_weapons"].append(wallet_next_weapon)
            except (json.JSONDecodeError, OSError):
                pass

        save_inventory(inventory)
        return inventory

    try:
        with INVENTORY_FILE.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except json.JSONDecodeError:
        raw_data = default_inventory()

    inventory = normalize_inventory(raw_data)
    save_inventory(inventory)
    return inventory


def save_inventory(inventory: dict[str, Any]) -> None:
    _ensure_data_dir()
    normalized = normalize_inventory(inventory)

    with INVENTORY_FILE.open("w", encoding="utf-8") as file:
        json.dump(normalized, file, ensure_ascii=False, indent=4)

    save_inventory_to_db(normalized)


def get_next_weapon() -> str:
    return load_inventory()["next_weapon"]


def set_next_weapon(weapon_name: str) -> dict[str, Any]:
    weapon = get_weapon_by_name(weapon_name)

    if weapon is None:
        raise ValueError(f"Arma inválida: {weapon_name}")

    inventory = load_inventory()
    inventory["next_weapon"] = weapon["name"]

    if weapon["name"] not in inventory["owned_weapons"]:
        inventory["owned_weapons"].append(weapon["name"])

    save_inventory(inventory)
    return inventory


def equip_owned_weapon(weapon_name: str) -> dict[str, Any]:
    inventory = load_inventory()
    if weapon_name not in inventory.get("owned_weapons", []):
        raise ValueError("Only owned weapons can be equipped.")
    inventory["next_weapon"] = weapon_name
    wallet = load_wallet()
    wallet["next_weapon"] = weapon_name
    save_wallet(wallet)
    save_inventory(inventory)
    return inventory


def register_weapon_purchase(weapon: dict[str, Any], session_id: int, balance_after_purchase: int) -> dict[str, Any]:
    inventory = set_next_weapon(weapon["name"])

    inventory["purchase_history"].append({
        "datetime": datetime.now().strftime(DATETIME_FORMAT),
        "session_id": int(session_id),
        "weapon": weapon["name"],
        "cost": int(weapon.get("cost", 0)),
        "balance_after_purchase": int(balance_after_purchase),
    })

    save_inventory(inventory)
    return inventory


def register_weapon_usage(weapon_name: str) -> dict[str, Any]:
    inventory = load_inventory()
    usage = inventory.setdefault("weapon_usage", {})
    usage[weapon_name] = int(usage.get(weapon_name, 0)) + 1
    save_inventory(inventory)
    return inventory


def get_weapon_by_choice(choice: str) -> dict[str, Any] | None:
    return get_weapons().get(choice)


def get_weapon_by_name(name: str) -> dict[str, Any] | None:
    for weapon in get_weapons().values():
        if weapon["name"].lower() == str(name).lower():
            return weapon

    return None


def list_weapons_with_status(wallet: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = load_inventory()
    owned_weapons = set(inventory.get("owned_weapons", []))
    owned_counts = build_owned_weapon_counts(inventory)
    next_weapon = inventory.get("next_weapon", get_default_weapon_name())
    items = []

    for key, weapon in get_weapons().items():
        items.append({
            "key": key,
            "name": weapon["name"],
            "cost": weapon["cost"],
            "available": can_buy_weapon(wallet, weapon),
            "owned": weapon["name"] in owned_weapons,
            "owned_quantity": int(owned_counts.get(weapon["name"], 0)),
            "selected_next": weapon["name"] == next_weapon,
            "group": get_weapon_group_name(weapon["name"]),
        })

    return items


def get_weapon_group_name(weapon_name: str) -> str:
    for group_name, names in WEAPON_GROUPS.items():
        if weapon_name in names:
            return group_name
    return "Other"


def build_owned_weapon_counts(inventory: dict[str, Any] | None = None) -> dict[str, int]:
    inventory = normalize_inventory(inventory or load_inventory())
    counts: dict[str, int] = {name: 0 for name in inventory.get("owned_weapons", [])}

    for item in inventory.get("purchase_history", []):
        if not isinstance(item, dict):
            continue
        weapon_name = str(item.get("weapon") or "").strip()
        if get_weapon_by_name(weapon_name) is None:
            continue
        counts[weapon_name] = int(counts.get(weapon_name, 0)) + 1

    for weapon_name in list(counts):
        if counts[weapon_name] <= 0:
            counts[weapon_name] = 1

    return counts


def purchase_weapons_batch(selection_counts: dict[str, int]) -> dict[str, Any]:
    wallet = load_wallet()
    inventory = load_inventory()
    normalized_selection: list[tuple[dict[str, Any], int]] = []
    total_cost = 0

    for weapon_name, raw_quantity in selection_counts.items():
        quantity = max(int(raw_quantity), 0)
        if quantity <= 0:
            continue
        weapon = get_weapon_by_name(weapon_name)
        if weapon is None:
            raise ValueError(f"Invalid weapon: {weapon_name}")
        if weapon["name"] == get_default_weapon_name():
            raise ValueError("Classic is owned by default and cannot be bought.")
        normalized_selection.append((weapon, quantity))
        total_cost += int(weapon.get("cost", 0)) * quantity

    if not normalized_selection:
        raise ValueError("Select at least one weapon to buy.")

    if total_cost > int(wallet.get("balance", 0)):
        raise ValueError("Not enough Coins to buy the current cart.")

    purchase_history = inventory.setdefault("purchase_history", [])
    owned_weapons = inventory.setdefault("owned_weapons", [])
    last_weapon_name = inventory.get("next_weapon", get_default_weapon_name())

    for weapon, quantity in normalized_selection:
        for _ in range(quantity):
            wallet = buy_weapon_with_kcred(wallet, weapon)
            weapon_name = str(weapon["name"])
            if weapon_name not in owned_weapons:
                owned_weapons.append(weapon_name)
            purchase_history.append({
                "datetime": datetime.now().strftime(DATETIME_FORMAT),
                "session_id": 0,
                "weapon": weapon_name,
                "cost": int(weapon.get("cost", 0)),
                "balance_after_purchase": int(wallet.get("balance", 0)),
                "source": "inventory_buy_all",
            })
            last_weapon_name = weapon_name

    inventory["next_weapon"] = last_weapon_name
    wallet["next_weapon"] = last_weapon_name
    save_wallet(wallet)
    save_inventory(inventory)
    return {
        "wallet": wallet,
        "inventory": inventory,
        "total_cost": total_cost,
        "selection_counts": {weapon["name"]: quantity for weapon, quantity in normalized_selection},
        "next_weapon": last_weapon_name,
    }


def sell_weapons_batch(selection_counts: dict[str, int]) -> dict[str, Any]:
    wallet = load_wallet()
    inventory = load_inventory()
    default_weapon = get_default_weapon_name()
    owned_counts = build_owned_weapon_counts(inventory)
    total_refund = 0

    for weapon_name, raw_quantity in selection_counts.items():
        quantity = max(int(raw_quantity), 0)
        if quantity <= 0:
            continue
        if weapon_name == default_weapon:
            raise ValueError("Classic cannot be sold.")
        weapon = get_weapon_by_name(weapon_name)
        if weapon is None:
            raise ValueError(f"Invalid weapon: {weapon_name}")
        if quantity > int(owned_counts.get(weapon_name, 0)):
            raise ValueError(f"Not enough owned copies of {weapon_name}.")
        total_refund += int(weapon.get("cost", 0)) * quantity
        owned_counts[weapon_name] -= quantity

        remaining = quantity
        history = inventory.get("purchase_history", [])
        for index in range(len(history) - 1, -1, -1):
            if remaining <= 0:
                break
            if str(history[index].get("weapon") or "") == weapon_name:
                history.pop(index)
                remaining -= 1

        if owned_counts[weapon_name] <= 0 and weapon_name in inventory["owned_weapons"]:
            inventory["owned_weapons"].remove(weapon_name)

    if total_refund <= 0:
        raise ValueError("Select at least one weapon to sell.")

    wallet["balance"] = max(int(wallet.get("balance", 0)) + total_refund, 0)
    wallet["total_spent"] = max(int(wallet.get("total_spent", 0)) - total_refund, 0)
    if inventory.get("next_weapon") not in inventory.get("owned_weapons", []):
        inventory["next_weapon"] = default_weapon
        wallet["next_weapon"] = default_weapon
    save_wallet(wallet)
    save_inventory(inventory)
    return {"wallet": wallet, "inventory": inventory, "total_refund": total_refund}


def build_inventory_summary() -> dict[str, Any]:
    inventory = load_inventory()
    weapons = get_weapons()

    return {
        "next_weapon": inventory["next_weapon"],
        "owned_weapons": inventory["owned_weapons"],
        "weapon_usage": inventory["weapon_usage"],
        "purchase_count": len(inventory["purchase_history"]),
        "weapon_count": len(weapons),
    }
