from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class InputAction:
    raw_input: str
    action: str
    group: str
    classification: str
    label: str


ACTION_ALIASES = {
    "alt_fire": "alternate_fire",
    "left": "strafe_left",
    "right": "strafe_right",
    "forward": "move_forward",
    "backward": "move_backward",
    "scroll_down": "scroll_jump",
}

LEGACY_ACTIONS = {
    "move_forward": "forward",
    "move_backward": "backward",
    "strafe_left": "left",
    "strafe_right": "right",
    "alternate_fire": "alt_fire",
}


DEFAULT_ACTIONS: dict[str, InputAction] = {
    "w": InputAction("w", "move_forward", "movement", "tracked", "W"),
    "a": InputAction("a", "strafe_left", "movement", "tracked", "A"),
    "s": InputAction("s", "move_backward", "movement", "tracked", "S"),
    "d": InputAction("d", "strafe_right", "movement", "tracked", "D"),
    "space": InputAction("space", "jump", "jump", "tracked", "Space"),
    "scroll_up": InputAction("scroll_up", "scroll_jump", "jump", "tracked", "Scroll"),
    "scroll_down": InputAction("scroll_down", "scroll_jump", "jump", "tracked", "Scroll"),
    "mouse_left": InputAction("mouse_left", "fire", "fire", "tracked", "LMB"),
    "mouse_right": InputAction("mouse_right", "alternate_fire", "alternate_fire", "tracked", "RMB"),
    "shift": InputAction("shift", "walk", "walk", "tracked", "Shift"),
    "ctrl": InputAction("ctrl", "crouch", "crouch", "tracked", "Ctrl"),
    "i": InputAction("i", "shop", "shop", "neutral", "I"),
    "p": InputAction("p", "inspect", "inspect", "neutral", "P"),
    "tab": InputAction("tab", "scoreboard", "scoreboard", "neutral", "Tab"),
    "m": InputAction("m", "map", "map", "neutral", "M"),
    "q": InputAction("q", "ability_q", "ability", "future", "Q"),
    "e": InputAction("e", "ability_e", "ability", "future", "E"),
    "c": InputAction("c", "ability_c", "ability", "future", "C"),
    "x": InputAction("x", "ultimate", "ability", "future", "X"),
    "z": InputAction("z", "ability_z", "ability", "future", "Z"),
    "v": InputAction("v", "ability_v", "ability", "future", "V"),
    "r": InputAction("r", "reload", "reload", "future", "R"),
    "f": InputAction("f", "interact", "interact", "future", "F"),
    "grave": InputAction("grave", "grave", "system", "future", "Grave"),
    "mouse_middle": InputAction("mouse_middle", "mouse_middle", "mouse", "future", "MMB"),
    "mouse_x1": InputAction("mouse_x1", "spray", "mouse", "future", "Mouse X1"),
    "mouse_x2": InputAction("mouse_x2", "mouse_extra", "mouse", "future", "Mouse X2"),
}


def canonical_action(action: str) -> str:
    normalized = str(action or "").strip().lower()
    return ACTION_ALIASES.get(normalized, normalized)


def legacy_action(action: str) -> str:
    normalized = canonical_action(action)
    return LEGACY_ACTIONS.get(normalized, normalized)


class InputActionCatalog:
    def __init__(self, actions: Mapping[str, InputAction] | None = None) -> None:
        self._actions = dict(actions or DEFAULT_ACTIONS)

    @classmethod
    def from_action_map(cls, action_map: Mapping[str, str] | None = None) -> "InputActionCatalog":
        actions = dict(DEFAULT_ACTIONS)
        for raw_input, raw_action in (action_map or {}).items():
            input_id = str(raw_input or "").strip().lower()
            action = canonical_action(raw_action)
            if not input_id or not action:
                continue

            default = actions.get(input_id)
            if default is None:
                actions[input_id] = InputAction(
                    raw_input=input_id,
                    action=action,
                    group=action,
                    classification="future",
                    label=input_id,
                )
                continue

            actions[input_id] = InputAction(
                raw_input=input_id,
                action=action,
                group=default.group,
                classification=default.classification,
                label=default.label,
            )
        return cls(actions)

    def resolve(self, raw_input: str) -> InputAction | None:
        return self._actions.get(str(raw_input or "").strip().lower())

    def to_action_map(self, *, legacy: bool = True) -> dict[str, str]:
        return {
            raw_input: legacy_action(action.action) if legacy else action.action
            for raw_input, action in self._actions.items()
        }
