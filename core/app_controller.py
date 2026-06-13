from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.dashboard import DashboardStats, build_dashboard_stats
from core.input_timing import InputTimingStats, InputTimingTracker
from core.inventory import (
    equip_owned_weapon,
    get_weapon_by_name,
    list_weapons_with_status,
    purchase_weapons_batch,
    sell_weapons_batch,
)
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
    session_mode: str = "deathmatch"
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
        self._runtime_revision = 0
        self._wallet_cache: dict[str, Any] | None = None
        self._available_weapons_cache: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def is_session_active(self) -> bool:
        return self.tracker.enabled

    @property
    def has_pending_purchase(self) -> bool:
        session = self.session_manager.last_finished_session
        has_dm_purchase = session is not None and session.session_mode == "deathmatch"
        return has_dm_purchase or self.state.has_pending_purchase

    @property
    def current_weapon(self) -> str:
        return self.session_manager.current_session_weapon

    @property
    def current_session_mode(self) -> str:
        return self.session_manager.current_session_mode

    @property
    def live_stats(self) -> ProtocolStats:
        return self.tracker.stats

    @property
    def live_input_stats(self) -> InputTimingStats:
        return self.input_timing.snapshot()

    @property
    def live_protocol_events(self) -> list[dict[str, Any]]:
        return list(self.tracker.recent_protocol_events())

    def get_live_protocol_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        return list(self.tracker.recent_protocol_events(limit))

    @property
    def current_diagonal_rule_mode(self) -> str:
        return self.tracker.current_diagonal_rule_mode

    @property
    def capture_mode(self) -> str:
        return str(getattr(self.input_timing, "capture_mode", "performance") or "performance")

    @property
    def is_capture_processing_enabled(self) -> bool:
        return bool(self.input_timing.enabled)

    @property
    def runtime_revision(self) -> int:
        return self._runtime_revision

    @property
    def current_session_kcreds(self) -> int:
        if self.current_session_mode == "ranked":
            return 0
        return calculate_session_kcreds(self.tracker.stats, self.tracker.config)

    @property
    def last_finished_session(self) -> DMResult | None:
        return self.session_manager.last_finished_session

    @property
    def current_session_config_snapshot(self) -> dict[str, Any]:
        return dict(self.session_manager.current_session_config_snapshot or {})

    def sync_state(self) -> AppState:
        self.state.is_session_active = self.is_session_active
        self.state.has_pending_purchase = self.has_pending_purchase
        self.state.current_weapon = self.current_weapon
        self.state.session_mode = self.current_session_mode
        self.state.last_finished_session = self.last_finished_session
        self._runtime_revision += 1
        return self.state

    def invalidate_cached_resources(self) -> None:
        self._wallet_cache = None
        self._available_weapons_cache = None

    # ------------------------------------------------------------------
    # Eventos de input
    # ------------------------------------------------------------------

    def handle_key_press(self, key_name: str) -> None:
        if not self.is_capture_processing_enabled:
            return
        self.input_timing.on_key_press(key_name)
        self.tracker.on_input_state_changed(self.input_timing.build_fire_context())

    def handle_key_release(self, key_name: str) -> None:
        if not self.is_capture_processing_enabled:
            return
        self.input_timing.on_key_release(key_name)
        self.tracker.on_input_state_changed(self.input_timing.build_fire_context())

    def handle_mouse_button(self, button_name: str, pressed: bool) -> None:
        if not self.is_capture_processing_enabled:
            return
        self.input_timing.on_mouse_button(button_name, pressed)

        if button_name == "mouse_left" and pressed:
            self.tracker.on_left_click(self.input_timing.build_fire_context())

    def handle_mouse_scroll(self, direction: str) -> None:
        if not self.is_capture_processing_enabled:
            return
        self.input_timing.on_scroll(direction)
        if direction == "scroll_up":
            self.tracker.on_jump_intent(self.input_timing.build_fire_context())

    def handle_left_click(self) -> None:
        # Compatibilidade com chamadas antigas. Para medir duração de tiro,
        # prefira handle_mouse_button("mouse_left", pressed).
        if not self.is_capture_processing_enabled:
            return
        self.tracker.on_left_click(self.input_timing.build_fire_context())

    # ------------------------------------------------------------------
    # Sessão
    # ------------------------------------------------------------------

    def start_session(self, session_mode: str = "deathmatch", start_source: str = "manual") -> dict[str, Any]:
        if self.has_pending_purchase:
            raise RuntimeError("Existe uma compra pendente antes da próxima sessão.")

        if self.is_session_active:
            raise RuntimeError("A sessão já está ativa.")

        self.tracker.stop()
        self.input_timing.reset()
        start_data = self.session_manager.start_session(
            session_mode=session_mode,
            start_source=start_source,
        )
        self.sync_state()
        return start_data

    def finish_session(self) -> DMResult:
        if not self.is_session_active:
            raise RuntimeError("Não existe sessão ativa para encerrar.")

        result = self.session_manager.finish_session()
        self.invalidate_cached_resources()
        self.state.has_pending_purchase = result.session_mode == "deathmatch"
        self.sync_state()
        return result

    def toggle_session(self) -> tuple[str, dict[str, Any] | DMResult]:
        if self.is_session_active:
            return "finished", self.finish_session()

        return "started", self.start_session()

    def reset_counters(self) -> None:
        was_active = self.is_session_active
        self.tracker.stop()
        self.tracker.reset_counters()
        self.input_timing.reset()
        if was_active:
            self.tracker.start(self.current_session_mode)
            self.input_timing.start()
        self.sync_state()

    def stop_without_saving(self) -> None:
        if self.tracker.enabled:
            self.tracker.stop()
        if self.input_timing.enabled:
            self.input_timing.stop()
        self.input_timing.reset()

        self.sync_state()

    def set_session_mode(self, session_mode: str) -> None:
        if self.is_session_active:
            raise RuntimeError("Não é possível trocar o modo com sessão ativa.")
        if self.has_pending_purchase:
            raise RuntimeError("Conclua a compra pendente antes de trocar o modo.")

        self.tracker.stop()
        self.tracker.reset_counters()
        self.input_timing.reset()
        self.session_manager.set_session_mode(session_mode)
        self.sync_state()

    # ------------------------------------------------------------------
    # Compra / arsenal
    # ------------------------------------------------------------------

    def get_available_weapons(self) -> list[dict[str, Any]]:
        if self._available_weapons_cache is None:
            self._available_weapons_cache = list_weapons_with_status(self.get_wallet())
        return [dict(item) for item in self._available_weapons_cache]

    def confirm_purchase_by_name(self, weapon_name: str) -> DMResult:
        weapon = get_weapon_by_name(weapon_name)

        if weapon is None:
            raise ValueError(f"Arma inválida: {weapon_name}")

        saved_session = self.session_manager.finish_purchase_and_save(weapon)

        if saved_session is None:
            raise RuntimeError("Não existe sessão finalizada aguardando compra.")

        self.invalidate_cached_resources()
        self.state.has_pending_purchase = False
        self.sync_state()
        return saved_session

    def confirm_purchase(self, weapon: dict[str, Any]) -> DMResult:
        return self.confirm_purchase_by_name(str(weapon.get("name", "")))

    def buy_inventory_cart(self, selection_counts: dict[str, int]) -> dict[str, Any]:
        summary = purchase_weapons_batch(selection_counts)
        self.invalidate_cached_resources()
        self.sync_state()
        return summary

    def sell_inventory_cart(self, selection_counts: dict[str, int]) -> dict[str, Any]:
        summary = sell_weapons_batch(selection_counts)
        self.invalidate_cached_resources()
        self.sync_state()
        return summary

    def equip_weapon(self, weapon_name: str) -> None:
        equip_owned_weapon(weapon_name)
        self.session_manager.current_session_weapon = weapon_name
        self.invalidate_cached_resources()
        self.sync_state()

    # ------------------------------------------------------------------
    # Consultas para UI
    # ------------------------------------------------------------------

    def get_wallet(self) -> dict[str, Any]:
        if self._wallet_cache is None:
            self._wallet_cache = load_wallet()
        return dict(self._wallet_cache)

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
