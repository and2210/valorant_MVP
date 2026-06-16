from __future__ import annotations

from dataclasses import asdict, dataclass, field

from core.input_actions import InputAction, canonical_action


BODY_IDLE = "idle"
BODY_MOVING = "moving"
BODY_BRAKING = "braking"
BODY_JUMPING = "jumping"

MOVEMENT_ACTIONS = {"move_forward", "move_backward", "strafe_left", "strafe_right"}
LATERAL_OPPOSITES = {
    "strafe_left": "strafe_right",
    "strafe_right": "strafe_left",
}


@dataclass(slots=True)
class TrainingStateSnapshot:
    body_state: str = BODY_IDLE
    active_actions: list[str] = field(default_factory=list)
    firing: bool = False
    firing_body_state: str = BODY_IDLE
    firing_while_moving: bool = False
    firing_while_jumping: bool = False
    firing_while_braking: bool = False
    movement_started_at: float = 0.0
    movement_stopped_at: float = 0.0
    brake_started_at: float = 0.0
    jump_started_at: float = 0.0
    jump_until: float = 0.0
    last_fire_at: float = 0.0
    last_fire_body_state: str = BODY_IDLE
    last_lateral_action: str = ""
    last_lateral_started_at: float = 0.0
    counter_strafe_attempts: int = 0
    fire_while_moving_count: int = 0
    fire_while_jumping_count: int = 0
    fire_while_braking_count: int = 0

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["movement_started_at"] = round(self.movement_started_at, 6)
        data["movement_stopped_at"] = round(self.movement_stopped_at, 6)
        data["brake_started_at"] = round(self.brake_started_at, 6)
        data["jump_started_at"] = round(self.jump_started_at, 6)
        data["jump_until"] = round(self.jump_until, 6)
        data["last_fire_at"] = round(self.last_fire_at, 6)
        data["last_lateral_started_at"] = round(self.last_lateral_started_at, 6)
        return data


class TrainingStateMachine:
    STABILIZATION_WINDOW_SECONDS = 0.14
    JUMP_WINDOW_SECONDS = 1.50

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.body_state = BODY_IDLE
        self.active_actions: set[str] = set()
        self.active_movement_actions: set[str] = set()
        self.firing = False
        self.firing_body_state = BODY_IDLE
        self.movement_started_at = 0.0
        self.movement_stopped_at = 0.0
        self.brake_started_at = 0.0
        self.jump_started_at = 0.0
        self.jump_until = 0.0
        self.last_fire_at = 0.0
        self.last_fire_body_state = BODY_IDLE
        self.last_lateral_action = ""
        self.last_lateral_started_at = 0.0
        self.counter_strafe_attempts = 0
        self.fire_while_moving_count = 0
        self.fire_while_jumping_count = 0
        self.fire_while_braking_count = 0

    def process(
        self,
        *,
        action: InputAction,
        event_type: str,
        monotonic_timestamp: float,
    ) -> TrainingStateSnapshot:
        if action.classification != "tracked":
            return self.snapshot(monotonic_timestamp)

        action_name = canonical_action(action.action)
        if event_type in {"key_down", "mouse_down"}:
            self._press(action_name, monotonic_timestamp)
        elif event_type in {"key_up", "mouse_up"}:
            self._release(action_name, monotonic_timestamp)
        elif event_type == "scroll":
            self._jump(monotonic_timestamp)

        self._derive_body_state(monotonic_timestamp)
        return self.snapshot(monotonic_timestamp)

    def snapshot(self, monotonic_timestamp: float | None = None) -> TrainingStateSnapshot:
        if monotonic_timestamp is not None:
            self._derive_body_state(monotonic_timestamp)
        return TrainingStateSnapshot(
            body_state=self.body_state,
            active_actions=sorted(self.active_actions),
            firing=self.firing,
            firing_body_state=self.firing_body_state,
            firing_while_moving=self.firing and self.firing_body_state == BODY_MOVING,
            firing_while_jumping=self.firing and self.firing_body_state == BODY_JUMPING,
            firing_while_braking=self.firing and self.firing_body_state == BODY_BRAKING,
            movement_started_at=self.movement_started_at,
            movement_stopped_at=self.movement_stopped_at,
            brake_started_at=self.brake_started_at,
            jump_started_at=self.jump_started_at,
            jump_until=self.jump_until,
            last_fire_at=self.last_fire_at,
            last_fire_body_state=self.last_fire_body_state,
            last_lateral_action=self.last_lateral_action,
            last_lateral_started_at=self.last_lateral_started_at,
            counter_strafe_attempts=self.counter_strafe_attempts,
            fire_while_moving_count=self.fire_while_moving_count,
            fire_while_jumping_count=self.fire_while_jumping_count,
            fire_while_braking_count=self.fire_while_braking_count,
        )

    def _press(self, action_name: str, now: float) -> None:
        self.active_actions.add(action_name)

        if action_name in MOVEMENT_ACTIONS:
            was_moving = bool(self.active_movement_actions)
            self.active_movement_actions.add(action_name)
            if not was_moving:
                self.movement_started_at = now

            opposite = LATERAL_OPPOSITES.get(action_name)
            if opposite and opposite == self.last_lateral_action:
                self.brake_started_at = now
                self.counter_strafe_attempts += 1
            if action_name in LATERAL_OPPOSITES:
                self.last_lateral_action = action_name
                self.last_lateral_started_at = now
            return

        if action_name in {"jump", "scroll_jump"}:
            self._jump(now)
            return

        if action_name == "fire":
            self._derive_body_state(now)
            self.firing = True
            self.firing_body_state = self.body_state
            self.last_fire_at = now
            self.last_fire_body_state = self.body_state
            if self.body_state == BODY_MOVING:
                self.fire_while_moving_count += 1
            elif self.body_state == BODY_JUMPING:
                self.fire_while_jumping_count += 1
            elif self.body_state == BODY_BRAKING:
                self.fire_while_braking_count += 1

    def _release(self, action_name: str, now: float) -> None:
        self.active_actions.discard(action_name)

        if action_name in MOVEMENT_ACTIONS:
            self.active_movement_actions.discard(action_name)
            if not self.active_movement_actions:
                self.movement_stopped_at = now
            return

        if action_name == "fire":
            self.firing = False
            self.firing_body_state = BODY_IDLE

    def _jump(self, now: float) -> None:
        self.active_actions.add("jump")
        self.jump_started_at = now
        self.jump_until = max(self.jump_until, now + self.JUMP_WINDOW_SECONDS)

    def _derive_body_state(self, now: float) -> None:
        if self.jump_until > 0 and now <= self.jump_until:
            self.body_state = BODY_JUMPING
            return

        if self.jump_until > 0 and now > self.jump_until:
            self.active_actions.discard("jump")

        if self.brake_started_at > 0 and (now - self.brake_started_at) < self.STABILIZATION_WINDOW_SECONDS:
            self.body_state = BODY_BRAKING
            return

        if self._has_opposing_lateral_pair():
            self.body_state = BODY_IDLE
            return

        if self.active_movement_actions:
            self.body_state = BODY_MOVING
            return

        self.body_state = BODY_IDLE

    def _has_opposing_lateral_pair(self) -> bool:
        return {"strafe_left", "strafe_right"}.issubset(self.active_movement_actions)
