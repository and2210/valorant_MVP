from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.dashboard import DashboardStats, build_dashboard_stats
from core.input_timing import InputTimingStats, InputTimingTracker
from core.inventory import get_weapon_by_name, list_weapons_with_status
from core.kcred_engine import calculate_session_kcreds
from core.models import DMResult
from core.persistence import load_wallet
from core.protocol_tracker import ProtocolStats, ProtocolTracker
from core.session_manager import SessionManager
from core.tracker_importer import TrackerImportResult, import_deathmatch_from_tracker, import_ranked_from_tracker


@dataclass
class AppState:
    is_session_active: bool = False
    has_pending_purchase: bool = False
    current_weapon: str = "Classic"
    last_finished_session: DMResult | None = None


class AppController:
    """
    Camada de controle do MVP APP.

    A interface, seja terminal ou GUI, deve chamar esta classe para iniciar sessão,
    encerrar sessão, resetar contadores, confirmar compra e consultar estado.
    Isso evita que a tela conheça detalhes internos de SessionManager,
    ProtocolTracker, carteira, inventário ou dashboard.
    """

    def __init__(self, tracker: ProtocolTracker | None = None) -> None:
        self.tracker = tracker or ProtocolTracker()
        self.input_timing = InputTimingTracker(self.tracker.config)
        self.session_manager = SessionManager(self.tracker, self.input_timing)
        self.state = AppState(current_weapon=self.session_manager.current_session_weapon)

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def is_session_active(self) -> bool:
        return self.tracker.enabled

    @property
    def has_pending_purchase(self) -> bool:
        pending = self.session_manager.last_finished_session
        return (
            (pending is not None and pending.session_mode == "dm_training")
            or self.state.has_pending_purchase
        )

    @property
    def current_weapon(self) -> str:
        return self.session_manager.current_session_weapon

    @property
    def live_stats(self) -> ProtocolStats:
        return self.tracker.stats

    @property
    def live_input_stats(self) -> InputTimingStats:
        return self.input_timing.snapshot()

    @property
    def current_session_kcreds(self) -> int:
        if self.session_manager.current_session_mode != "dm_training":
            return 0
        return calculate_session_kcreds(self.tracker.stats, self.tracker.config)

    @property
    def last_finished_session(self) -> DMResult | None:
        return self.session_manager.last_finished_session

    def sync_state(self) -> AppState:
        self.state.is_session_active = self.is_session_active
        self.state.has_pending_purchase = self.has_pending_purchase
        self.state.current_weapon = self.current_weapon
        self.state.last_finished_session = self.last_finished_session
        return self.state

    # ------------------------------------------------------------------
    # Eventos de input
    # ------------------------------------------------------------------

    def handle_key_press(self, key_name: str) -> None:
        self.input_timing.on_key_press(key_name)
        self.tracker.on_key_press(key_name)
        self.sync_state()

    def handle_key_release(self, key_name: str) -> None:
        self.input_timing.on_key_release(key_name)
        self.tracker.on_key_release(key_name)
        self.sync_state()

    def handle_mouse_button(self, button_name: str, pressed: bool) -> None:
        self.input_timing.on_mouse_button(button_name, pressed)

        if button_name == "mouse_left" and pressed:
            self.tracker.on_left_click()

        self.sync_state()

    def handle_mouse_scroll(self, direction: str) -> None:
        self.input_timing.on_scroll(direction)
        self.sync_state()

    def handle_left_click(self) -> None:
        # Compatibilidade com chamadas antigas. Para medir duração de tiro,
        # prefira handle_mouse_button("mouse_left", pressed).
        self.tracker.on_left_click()
        self.sync_state()

    # ------------------------------------------------------------------
    # Sessão
    # ------------------------------------------------------------------

    def start_session(self, session_mode: str = "dm_training", training_method: str = "") -> dict[str, Any]:
        if self.has_pending_purchase:
            raise RuntimeError("Existe uma compra pendente antes da próxima sessão.")

        if self.is_session_active:
            raise RuntimeError("A sessão já está ativa.")

        start_data = self.session_manager.start_session(
            session_mode=session_mode,
            training_method=training_method,
        )
        self.sync_state()
        return start_data

    def finish_session(self) -> DMResult:
        if not self.is_session_active:
            raise RuntimeError("Não existe sessão ativa para encerrar.")

        result = self.session_manager.finish_session()
        self.state.has_pending_purchase = result.session_mode == "dm_training"
        self.sync_state()
        return result

    def toggle_session(self) -> tuple[str, dict[str, Any] | DMResult]:
        if self.is_session_active:
            return "finished", self.finish_session()

        return "started", self.start_session()

    def reset_counters(self) -> None:
        self.tracker.reset_counters()
        if self.input_timing.enabled:
            session_ref = self.input_timing.session_ref
            self.input_timing.start(
                session_ref=session_ref,
                session_mode=self.session_manager.current_session_mode,
                training_method=self.session_manager.current_training_method,
            )
        else:
            self.input_timing.reset()
        self.sync_state()

    def stop_without_saving(self) -> None:
        if self.tracker.enabled:
            self.tracker.stop()
        if self.input_timing.enabled:
            self.input_timing.stop()

        self.sync_state()

    # ------------------------------------------------------------------
    # Compra / arsenal
    # ------------------------------------------------------------------

    def get_available_weapons(self) -> list[dict[str, Any]]:
        return list_weapons_with_status(load_wallet())

    def confirm_purchase_by_name(self, weapon_name: str) -> DMResult:
        weapon = get_weapon_by_name(weapon_name)

        if weapon is None:
            raise ValueError(f"Arma inválida: {weapon_name}")

        saved_session = self.session_manager.finish_purchase_and_save(weapon)

        if saved_session is None:
            raise RuntimeError("Não existe sessão finalizada aguardando compra.")

        self.state.has_pending_purchase = False
        self.sync_state()
        return saved_session

    def confirm_purchase(self, weapon: dict[str, Any]) -> DMResult:
        return self.confirm_purchase_by_name(str(weapon.get("name", "")))

    # ------------------------------------------------------------------
    # Consultas para UI
    # ------------------------------------------------------------------

    def get_wallet(self) -> dict[str, Any]:
        return load_wallet()

    def get_dashboard(self) -> DashboardStats:
        return build_dashboard_stats()

    def import_tracker_deathmatches(
        self,
        import_all: bool = False,
        progress_callback=None,
        start_date=None,
        end_date=None,
        replace_date_range: bool = False,
    ) -> TrackerImportResult:
        return import_deathmatch_from_tracker(
            import_all=import_all,
            progress_callback=progress_callback,
            start_date=start_date,
            end_date=end_date,
            replace_date_range=replace_date_range,
        )


# Compatibilidade incremental: método anexado para importar rankeds sem alterar o fluxo existente.
def _app_controller_import_tracker_rankeds(
    self,
    import_all: bool = False,
    progress_callback=None,
    start_date=None,
    end_date=None,
    replace_date_range: bool = False,
) -> TrackerImportResult:
    return import_ranked_from_tracker(
        import_all=import_all,
        progress_callback=progress_callback,
        start_date=start_date,
        end_date=end_date,
        replace_date_range=replace_date_range,
    )


AppController.import_tracker_rankeds = _app_controller_import_tracker_rankeds
