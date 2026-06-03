from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

from pynput import keyboard, mouse

from core.app_controller import AppController
from core.input_timing import InputTimingTracker
from core.sqlite_store import ensure_sqlite_seeded_from_files
from core.history import build_history_summary, get_recent_sessions
from ui.console_ui import (
    choose_next_weapon,
    print_purchase_saved,
    print_session_finished,
    print_session_started,
    print_startup,
    print_summary,
    print_history_summary,
    print_inventory_summary,
    print_dashboard,
    show_wallet,
)


APP_NAME = "MVP-KCred"


class AppContext:
    def __init__(self) -> None:
        ensure_sqlite_seeded_from_files()
        self.controller = AppController()
        self.session_finished_event = threading.Event()
        self.shutdown_event = threading.Event()
        self.keyboard_listener = None
        self.mouse_listener = None


app_context = AppContext()


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_runtime_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent


def write_launch_error(error: BaseException) -> Path:
    log_path = get_runtime_dir() / "launch_error.log"

    with log_path.open("w", encoding="utf-8") as file:
        file.write(f"{APP_NAME} falhou ao iniciar.\n")
        file.write("\n")
        file.write("Erro:\n")
        file.write(f"{type(error).__name__}: {error}\n")
        file.write("\n")
        file.write("Traceback:\n")
        file.write(traceback.format_exc())

    return log_path


def get_key_name(key) -> str:
    try:
        return key.char.lower()
    except AttributeError:
        return str(key)


def toggle_session() -> None:
    if not app_context.controller.is_session_active:
        start_data = app_context.controller.start_session()
        print_session_started(start_data)
        return

    session_data = app_context.controller.finish_session()
    print_session_finished(session_data)
    app_context.session_finished_event.set()


def on_key_press(key):
    key_name = get_key_name(key)

    if key == keyboard.Key.f9:
        app_context.controller.reset_counters()
        print("\nContadores da sessão resetados.\n")
        return

    if key == keyboard.Key.f10:
        toggle_session()
        return

    if key == keyboard.Key.f8:
        print_history_summary(build_history_summary(), get_recent_sessions())
        return

    if key == keyboard.Key.f7:
        print_inventory_summary()
        return

    if key == keyboard.Key.f6:
        print_dashboard(app_context.controller.get_dashboard())
        return

    if key == keyboard.Key.f11:
        show_wallet(app_context.controller.get_wallet())
        return

    if key == keyboard.Key.f12:
        if app_context.controller.is_session_active:
            app_context.controller.stop_without_saving()

        print_summary(
            session_data=None,
            tracker_enabled=app_context.controller.is_session_active,
            current_weapon=app_context.controller.current_weapon,
            stats=app_context.controller.live_stats,
        )
        show_wallet(app_context.controller.get_wallet())
        print("Encerrando contador...")

        if app_context.mouse_listener is not None:
            app_context.mouse_listener.stop()

        app_context.shutdown_event.set()
        return False

    app_context.controller.handle_key_press(key_name)


def on_key_release(key):
    key_name = get_key_name(key)
    app_context.controller.handle_key_release(key_name)


def on_click(x, y, button, pressed):
    button_name = InputTimingTracker.mouse_button_to_input_id(button)
    app_context.controller.handle_mouse_button(button_name, bool(pressed))


def on_scroll(x, y, dx, dy):
    if dy > 0:
        app_context.controller.handle_mouse_scroll("scroll_up")
    elif dy < 0:
        app_context.controller.handle_mouse_scroll("scroll_down")


def finish_session_purchase_and_save() -> None:
    if app_context.controller.last_finished_session is None:
        return

    session_data = app_context.controller.last_finished_session

    print("\n==============================")
    print("KCRED ADICIONADO")
    print("==============================")
    print(f"Sessão: {session_data.session_id}")
    print(f"Arma usada: {session_data.weapon_used}")
    print(f"KCreds ganhos: {session_data.kcreds_earned}")
    print(f"Saldo após ganho: {session_data.balance_after_earning} KCreds")
    print("==============================\n")

    weapon = choose_next_weapon()
    saved_session = app_context.controller.confirm_purchase(weapon)

    if saved_session is not None:
        print_purchase_saved(saved_session)


def run_console() -> None:
    wallet = app_context.controller.get_wallet()
    print_startup(wallet)

    app_context.keyboard_listener = keyboard.Listener(
        on_press=on_key_press,
        on_release=on_key_release,
    )

    app_context.mouse_listener = mouse.Listener(
        on_click=on_click,
        on_scroll=on_scroll,
    )

    app_context.keyboard_listener.start()
    app_context.mouse_listener.start()

    while not app_context.shutdown_event.is_set():
        if app_context.session_finished_event.wait(timeout=0.2):
            app_context.session_finished_event.clear()
            finish_session_purchase_and_save()

    if app_context.mouse_listener.running:
        app_context.mouse_listener.stop()

    if app_context.keyboard_listener.running:
        app_context.keyboard_listener.stop()


def run_gui() -> None:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from ui.main_window import MainWindow
    except ImportError as error:
        print("\nPySide6 não está instalado ou não pôde ser carregado.")
        print("Instale com:")
        print("python -m pip install PySide6")
        print(f"\nDetalhe técnico: {error}\n")
        raise

    app = QApplication(sys.argv)

    try:
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as error:
        log_path = write_launch_error(error)
        QMessageBox.critical(
            None,
            "Erro ao iniciar o MVP-KCred",
            f"O aplicativo encontrou um erro ao iniciar.\n\nLog salvo em:\n{log_path}",
        )
        raise


def should_run_gui_by_default(args: set[str]) -> bool:
    if "--terminal" in args or "terminal" in args or "--console" in args or "console" in args:
        return False

    if "--gui" in args or "gui" in args:
        return True

    # No executável Windows, abrir GUI por padrão.
    if is_frozen():
        return True

    # No Python normal, manter comportamento antigo: terminal por padrão.
    return False


def main() -> None:
    args = {arg.lower() for arg in sys.argv[1:]}

    if should_run_gui_by_default(args):
        run_gui()
        return

    run_console()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        log_path = write_launch_error(error)

        if not is_frozen():
            raise

        # Em .exe sem console, esse log é a principal forma de descobrir a causa.
        # A GUI também tenta mostrar uma QMessageBox quando possível.
        sys.exit(1)
