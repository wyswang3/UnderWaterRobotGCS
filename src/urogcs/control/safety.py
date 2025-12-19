# src/urogcs/control/safety.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Optional
import time


@dataclass
class SafetyConfig:
    """
    GCS-side safety policy (pre-send).
    This is NOT the final safety wall; ROV side must still enforce TTL/estop/failsafe.

    - deadzone: small joystick/keyboard noise ignore
    - max_abs: clamp DOF command to [-max_abs, +max_abs]
    - max_step: per-axis slew-rate limit per tick (helps reduce sudden jumps)
    - require_link_alive_ms: if no telemetry/recv for too long, force command to zero
    """
    deadzone: float = 0.05
    max_abs: float = 1.0
    max_step: float = 0.20

    require_link_alive_ms: int = 1200
    soft_zero_on_link_loss: bool = True


Dof6 = Tuple[float, float, float, float, float, float]  # surge,sway,heave,roll,pitch,yaw


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _apply_deadzone(x: float, dz: float) -> float:
    if abs(x) < dz:
        return 0.0
    return x


@dataclass
class SafetyState:
    last_cmd: Dof6 = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    last_good_rx_ns: int = 0  # time.monotonic_ns of last telemetry/any rx


class SafetyPolicy:
    def __init__(self, cfg: SafetyConfig = SafetyConfig()) -> None:
        self.cfg = cfg
        self.st = SafetyState()

    def note_rx(self, rx_ns: Optional[int] = None) -> None:
        self.st.last_good_rx_ns = int(rx_ns if rx_ns is not None else time.monotonic_ns())

    def link_ok(self) -> bool:
        if self.st.last_good_rx_ns == 0:
            return False
        age_ms = (time.monotonic_ns() - self.st.last_good_rx_ns) / 1_000_000.0
        return age_ms <= float(self.cfg.require_link_alive_ms)

    def sanitize_dof(self, cmd: Dof6) -> Dof6:
        # 1) deadzone + clamp
        dz = float(self.cfg.deadzone)
        lim = float(self.cfg.max_abs)
        x = tuple(_clamp(_apply_deadzone(float(v), dz), -lim, +lim) for v in cmd)  # type: ignore

        # 2) slew-rate limit
        ms = float(self.cfg.max_step)
        last = self.st.last_cmd
        y = []
        for i in range(6):
            target = x[i]
            prev = float(last[i])
            delta = _clamp(target - prev, -ms, +ms)
            y.append(prev + delta)

        out = (y[0], y[1], y[2], y[3], y[4], y[5])
        self.st.last_cmd = out
        return out

    def maybe_force_zero_on_link_loss(self, cmd: Dof6) -> Dof6:
        if not self.cfg.soft_zero_on_link_loss:
            return cmd
        if self.link_ok():
            return cmd
        # If link not ok: send zeroed commands (do not latch estop here; leave that to operator)
        self.st.last_cmd = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        return self.st.last_cmd
