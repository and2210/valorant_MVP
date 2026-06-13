from __future__ import annotations

from typing import Any

from core.config import AppConfig, load_config


def calculate_kcreds(clean_hits: int, kcred_per_clean_hit: int | None = None) -> int:
    """
    Compatibilidade com chamadas antigas: calcula KCred bruto somente por acerto limpo.
    Para sessão real, prefira calculate_session_kcreds(), que aplica penalidades.
    """
    if kcred_per_clean_hit is None:
        kcred_per_clean_hit = load_config().kcred_per_clean_hit

    return max(int(clean_hits), 0) * max(int(kcred_per_clean_hit), 0)


def calculate_session_kcreds(stats: Any, config: AppConfig | None = None) -> int:
    """
    Calcula KCred líquido da sessão.

    Regra v0.20.3:
    - acerto limpo soma KCred;
    - erro válido reduz o KCred da sessão;
    - o valor não fica negativo nesta fase, para não retirar saldo antigo do jogador.
    """
    config = config or load_config()

    gross = calculate_kcreds(getattr(stats, "clean_hits", 0), config.kcred_per_clean_hit)
    penalty = calculate_session_kcred_penalty(stats, config)

    return max(gross - penalty, 0)


def calculate_session_kcred_penalty(stats: Any, config: AppConfig | None = None) -> int:
    config = config or load_config()

    brake_errors = max(int(getattr(stats, "brake_errors", 0)), 0)
    diagonal_errors = max(int(getattr(stats, "diagonal_errors", 0)), 0)
    no_ad_errors = max(int(getattr(stats, "no_ad_errors", 0)), 0)

    return (
        brake_errors * max(int(config.kcred_penalty_brake_error), 0)
        + diagonal_errors * max(int(config.kcred_penalty_diagonal_error), 0)
        + no_ad_errors * max(int(config.kcred_penalty_no_ad_error), 0)
    )


def apply_session_earning(wallet: dict, earned: int) -> tuple[dict, int, int]:
    balance_before = max(int(wallet.get("balance", 0)), 0)

    wallet["balance"] = balance_before + earned
    wallet["total_earned"] = int(wallet.get("total_earned", 0)) + earned
    wallet["session_count"] = int(wallet.get("session_count", 0)) + 1

    return wallet, balance_before, wallet["balance"]


def can_buy_weapon(wallet: dict, weapon: dict) -> bool:
    return int(weapon.get("cost", 0)) <= int(wallet.get("balance", 0))


def buy_weapon(wallet: dict, weapon: dict) -> dict:
    cost = int(weapon.get("cost", 0))
    balance = max(int(wallet.get("balance", 0)), 0)

    if cost > balance:
        raise ValueError("Saldo insuficiente para comprar esta arma.")

    wallet["balance"] = max(balance - cost, 0)
    wallet["total_spent"] = int(wallet.get("total_spent", 0)) + cost
    wallet["next_weapon"] = weapon.get("name", "Classic")

    return wallet
