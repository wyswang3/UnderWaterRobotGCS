# src/urogcs/control/keyboard_mapper.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Set

from urogcs.protocol.messages import DofCommand


@dataclass
class KeyProfile:
    """
    Keyboard mapping profile.
    step: per-tick increment in normalized [-1,1] space.
    decay: when key not pressed, command decays toward 0 (0..1).
    """
    step: float = 0.08
    decay: float = 0.85


DEFAULT_BINDINGS: Dict[str, str] = {
    # translation
    "w": "surge+",
    "s": "surge-",
    "a": "sway-",
    "d": "sway+",
    "r": "heave+",
    "f": "heave-",
    # rotation
    "q": "yaw-",
    "e": "yaw+",
    "j": "roll-",
    "l": "roll+",
    "i": "pitch+",
    "k": "pitch-",
    # safety / mode (handled by app layer typically)
    # "space": "estop",
    # "tab": "arm_toggle",
}


class KeyboardMapper:
    """
    Stateful mapper: keeps last command and updates with key presses.
    App layer provides currently pressed keys each tick.
    """
    def __init__(self, profile: KeyProfile | None = None, bindings: Dict[str, str] | None = None) -> None:
        self.profile = profile or KeyProfile()
        self.bindings = bindings or dict(DEFAULT_BINDINGS)
        self.cmd = DofCommand()

    def _apply_decay(self) -> None:
        p = self.profile.decay
        self.cmd.surge *= p
        self.cmd.sway *= p
        self.cmd.heave *= p
        self.cmd.roll *= p
        self.cmd.pitch *= p
        self.cmd.yaw *= p

    def update(self, pressed: Iterable[str]) -> DofCommand:
        """
        pressed: iterable of key names (e.g., {"w","a","q"}).
        Returns a new command snapshot (also stored internally).
        """
        pressed_set: Set[str] = set(pressed)

        # decay first (smooth stop)
        self._apply_decay()

        step = self.profile.step

        # apply bindings
        for k in pressed_set:
            act = self.bindings.get(k)
            if not act:
                continue
            if act == "surge+":
                self.cmd.surge += step
            elif act == "surge-":
                self.cmd.surge -= step
            elif act == "sway+":
                self.cmd.sway += step
            elif act == "sway-":
                self.cmd.sway -= step
            elif act == "heave+":
                self.cmd.heave += step
            elif act == "heave-":
                self.cmd.heave -= step
            elif act == "roll+":
                self.cmd.roll += step
            elif act == "roll-":
                self.cmd.roll -= step
            elif act == "pitch+":
                self.cmd.pitch += step
            elif act == "pitch-":
                self.cmd.pitch -= step
            elif act == "yaw+":
                self.cmd.yaw += step
            elif act == "yaw-":
                self.cmd.yaw -= step

        self.cmd.clamp(-1.0, 1.0)
        return DofCommand(
            surge=self.cmd.surge,
            sway=self.cmd.sway,
            heave=self.cmd.heave,
            roll=self.cmd.roll,
            pitch=self.cmd.pitch,
            yaw=self.cmd.yaw,
        )
