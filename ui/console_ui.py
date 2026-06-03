from core.config import SESSIONS_FILE, load_config
from core.dashboard import DashboardStats
from core.history import HistorySummary
from core.inventory import build_inventory_summary, get_next_weapon, get_weapon_by_choice, list_weapons_with_status
from core.kcred_engine import can_buy_weapon
from core.models import DMResult
from core.persistence import load_wallet


def print_startup(wallet: dict) -> None:
    print("\nCONTADOR DE FREIO — RADIANTE / KCRED")
    print("------------------------------------")
    print("Status inicial: DESLIGADO")
    print(f"Saldo atual: {wallet['balance']} KCreds")
    print(f"Próxima arma: {get_next_weapon()}")
    print("------------------------------------")
    print("Regra atual — Nível 1:")
    print("A -> D -> clique = acerto limpo")
    print("D -> A -> clique = acerto limpo")
    print("A/D + W/S junto = erro diagonal")
    print("W/S -> clique sem A/D = erro sem A/D")
    print("A/D -> clique sem tecla oposta = erro de freio")
    print("------------------------------------")
    print(f"KCred por acerto limpo: {load_config().kcred_per_clean_hit}")
    print("------------------------------------")
    print("F10 = iniciar/encerrar sessão")
    print("F9  = resetar contadores da sessão")
    print("F8  = mostrar histórico")
    print("F7  = mostrar arsenal")
    print("F6  = mostrar dashboard")
    print("F11 = mostrar carteira")
    print("F12 = mostrar resumo e sair")
    print("------------------------------------\n")


def show_wallet(wallet: dict) -> None:
    print("\n==============================")
    print("CARTEIRA KCRED")
    print("==============================")
    print(f"Saldo atual: {wallet['balance']} KCreds")
    print(f"Próxima arma: {get_next_weapon()}")
    print(f"Total ganho: {wallet['total_earned']} KCreds")
    print(f"Total gasto: {wallet['total_spent']} KCreds")
    print(f"Sessões registradas: {wallet['session_count']}")
    print("==============================\n")


def print_inventory_summary() -> None:
    summary = build_inventory_summary()

    print("\n==============================")
    print("ARSENAL / INVENTÁRIO")
    print("==============================")
    print(f"Próxima arma: {summary['next_weapon']}")
    print(f"Armas no catálogo: {summary['weapon_count']}")
    print(f"Armas já usadas/compradas: {len(summary['owned_weapons'])}")
    print(f"Compras registradas: {summary['purchase_count']}")

    if summary['owned_weapons']:
        print("------------------------------")
        print("Arsenal:")
        for weapon_name in summary['owned_weapons']:
            usage = summary['weapon_usage'].get(weapon_name, 0)
            print(f"{weapon_name:<8} | usos: {usage}")

    print("==============================\n")


def print_session_started(start_data: dict) -> None:
    print("\n[F10] Sessão INICIADA.")
    print(f"Arma desta sessão: {start_data['weapon']}")
    print(f"Saldo atual: {start_data['balance']} KCreds")
    print("Contagem ligada. Jogue o DM normalmente.\n")


def print_summary(
    session_data,
    tracker_enabled: bool,
    current_weapon: str,
    stats=None,
) -> None:
    if session_data:
        clean_hits = session_data.clean_hits
        brake_errors = session_data.brake_errors
        diagonal_errors = session_data.diagonal_errors
        no_ad_errors = session_data.no_ad_errors
        valid_attempts = session_data.valid_attempts
        ignored_clicks = session_data.ignored_clicks
        clicks_holding = session_data.clicks_while_holding_lateral
        protocol_rate = session_data.protocol_rate
        kcreds = session_data.kcreds_earned
        weapon = session_data.weapon_used
    elif stats is not None:
        clean_hits = stats.clean_hits
        brake_errors = stats.brake_errors
        diagonal_errors = stats.diagonal_errors
        no_ad_errors = stats.no_ad_errors
        valid_attempts = stats.valid_attempts
        ignored_clicks = stats.ignored_clicks
        clicks_holding = stats.clicks_while_holding_lateral
        protocol_rate = round(stats.protocol_rate, 1)
        kcreds = clean_hits * load_config().kcred_per_clean_hit
        weapon = current_weapon
    else:
        clean_hits = 0
        brake_errors = 0
        diagonal_errors = 0
        no_ad_errors = 0
        valid_attempts = 0
        ignored_clicks = 0
        clicks_holding = 0
        protocol_rate = 0.0
        kcreds = 0
        weapon = current_weapon

    status = "LIGADO" if tracker_enabled else "DESLIGADO"

    print("\n==============================")
    print("RESUMO DO TREINO")
    print("==============================")
    print(f"Status da contagem: {status}")
    print(f"Arma da sessão: {weapon}")
    print(f"Acertos limpos: {clean_hits}")
    print(f"Erros de freio: {brake_errors}")
    print(f"Erros de diagonal: {diagonal_errors}")
    print(f"Erros sem A/D: {no_ad_errors}")
    print(f"Tentativas válidas: {valid_attempts}")
    print(f"Cliques ignorados: {ignored_clicks}")
    print(f"Cliques segurando A/D: {clicks_holding}")
    print(f"Taxa de protocolo limpo: {protocol_rate:.1f}%")
    print(f"KCreds ganhos: {kcreds}")
    print("==============================\n")


def print_session_finished(session_data) -> None:
    print("\n[F10] Sessão ENCERRADA.")
    print_summary(session_data, tracker_enabled=False, current_weapon=session_data.weapon_used)


def print_weapon_menu(wallet: dict) -> None:
    print("\n==============================")
    print("MENU DE COMPRA — PRÓXIMO DM")
    print("==============================")
    print(f"Saldo disponível: {wallet['balance']} KCreds")
    print("------------------------------")

    for item in list_weapons_with_status(wallet):
        status = "DISPONÍVEL" if item["available"] else "SEM SALDO"
        selected_marker = " <- PRÓXIMA" if item.get("selected_next") else ""
        owned_marker = " | ARSENAL" if item.get("owned") else ""
        print(
            f"{item['key']} - {item['name']:<8} | "
            f"{item['cost']:>4} KCreds | {status}{owned_marker}{selected_marker}"
        )

    print("------------------------------")
    print("ENTER = Classic")
    print("==============================")


def choose_next_weapon() -> dict:
    while True:
        wallet = load_wallet()
        print_weapon_menu(wallet)
        choice = input("Escolha a arma do próximo DM: ").strip()

        if choice == "":
            choice = "0"

        weapon = get_weapon_by_choice(choice)

        if weapon is None:
            print("Opção inválida. Escolha um número do menu.")
            continue

        if not can_buy_weapon(wallet, weapon):
            print(f"Saldo insuficiente para comprar {weapon['name']}.")
            continue

        return weapon


def print_purchase_saved(session_data) -> None:
    print("\nCompra registrada.")
    print(f"Próxima arma: {session_data.weapon_bought_next}")
    print(f"Custo: {session_data.weapon_cost} KCreds")
    print(f"Saldo restante: {session_data.balance_final} KCreds")
    print("\nSessão adicionada à planilha:")
    print(SESSIONS_FILE)
    print("Pronto para o próximo DM.\n")


def print_recent_sessions(sessions: list[DMResult]) -> None:
    if not sessions:
        print("Nenhuma sessão encontrada no histórico.")
        return

    print("\nÚLTIMAS SESSÕES")
    print("------------------------------")

    for session in sessions:
        print(
            f"#{session.session_id} | {session.finished_at} | "
            f"{session.weapon_used} | "
            f"limpos {session.clean_hits} | "
            f"taxa {session.protocol_rate:.1f}% | "
            f"+{session.kcreds_earned} KCred"
        )


def print_history_summary(summary: HistorySummary, recent_sessions: list[DMResult]) -> None:
    print("\n==============================")
    print("HISTÓRICO DO TREINO")
    print("==============================")
    print(f"Sessões totais: {summary.total_sessions}")
    print(f"Acertos limpos totais: {summary.total_clean_hits}")
    print(f"Erros de freio totais: {summary.total_brake_errors}")
    print(f"Erros de diagonal totais: {summary.total_diagonal_errors}")
    print(f"Erros sem A/D totais: {summary.total_no_ad_errors}")
    print(f"Tentativas válidas totais: {summary.total_valid_attempts}")
    print(f"KCreds ganhos no histórico: {summary.total_kcreds_earned}")
    print(f"Taxa média de protocolo: {summary.average_protocol_rate:.1f}%")

    if summary.best_protocol_session_id:
        print(
            "Melhor taxa: "
            f"{summary.best_protocol_rate:.1f}% "
            f"na sessão #{summary.best_protocol_session_id} "
            f"com {summary.best_protocol_weapon}"
        )

    if summary.best_clean_hits_session_id:
        print(
            "Maior volume limpo: "
            f"{summary.best_clean_hits} acertos "
            f"na sessão #{summary.best_clean_hits_session_id} "
            f"com {summary.best_clean_hits_weapon}"
        )

    if summary.sessions_by_weapon:
        print("------------------------------")
        print("Sessões por arma:")
        for weapon, count in summary.sessions_by_weapon.items():
            average = summary.average_protocol_by_weapon.get(weapon, 0.0)
            print(f"{weapon:<8} | {count:>3} sessões | média {average:.1f}%")

    print_recent_sessions(recent_sessions)
    print("==============================\n")


def _progress_bar(rate: float, size: int = 20) -> str:
    filled = int((max(min(rate, 100.0), 0.0) / 100.0) * size)
    return "█" * filled + "░" * (size - filled)


def print_dashboard(stats: DashboardStats) -> None:
    print("\n==============================")
    print("MVP APP — DASHBOARD")
    print("==============================")
    print(f"Nível: {stats.progress.level}")
    print(
        "XP: "
        f"{stats.progress.current_level_xp} / {stats.progress.next_level_xp} "
        f"[{_progress_bar(stats.progress.progress_rate)}] "
        f"{stats.progress.progress_rate:.1f}%"
    )
    print(f"XP total: {stats.progress.total_xp}")
    print("------------------------------")
    print(f"Saldo: {stats.balance} KCreds")
    print(f"Próxima arma: {stats.next_weapon}")
    print(f"Arsenal: {stats.owned_weapon_count} / {stats.inventory_weapon_count} armas")
    print("------------------------------")
    print(f"Sessões totais: {stats.total_sessions}")
    print(f"Acertos limpos totais: {stats.total_clean_hits}")
    print(f"Tentativas válidas totais: {stats.total_valid_attempts}")
    print(f"Taxa média geral: {stats.average_protocol_rate:.1f}%")

    if stats.best_weapon:
        print(f"Melhor arma: {stats.best_weapon} ({stats.best_weapon_rate:.1f}%)")

    if stats.best_session_id:
        print(f"Melhor sessão: #{stats.best_session_id} ({stats.best_session_rate:.1f}%)")

    print("------------------------------")
    print("Hoje:")
    print(f"Sessões: {stats.today.sessions}")
    print(f"Acertos limpos: {stats.today.clean_hits}")
    print(f"Tentativas válidas: {stats.today.valid_attempts}")
    print(f"Taxa média: {stats.today.average_protocol_rate:.1f}%")
    print(f"KCreds ganhos: {stats.today.kcreds_earned}")

    if stats.last_session is not None:
        last = stats.last_session
        print("------------------------------")
        print("Última sessão:")
        print(
            f"#{last.session_id} | {last.finished_at} | {last.weapon_used} | "
            f"taxa {last.protocol_rate:.1f}% | +{last.kcreds_earned} KCred"
        )

    print("==============================\n")
