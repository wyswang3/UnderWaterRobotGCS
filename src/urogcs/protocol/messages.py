# src/urogcs/protocol/messages.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List

@dataclass
class DofCommand:
    surge: float = 0.0
    sway:  float = 0.0
    heave: float = 0.0
    roll:  float = 0.0
    pitch: float = 0.0
    yaw:   float = 0.0
    def as_list6(self) -> List[float]:
        return [self.surge, self.sway, self.heave, self.roll, self.pitch, self.yaw]

@dataclass
class StatusTelemetry:
    session_established: int = 0
    link_alive: int = 0
    estop: int = 0
    mode: int = 0
    active_controller: str = ""
    desired_controller: str = ""
    consecutive_failures: int = 0
    auto_fail_limit: int = 0
    t_ns: int = 0

def clamp_cstr(s: str, cap: int) -> bytes:
    b = (s or "").encode("utf-8", errors="ignore")
    b = b[: max(0, cap - 1)]
    return b + b"\x00" + (b"\x00" * (cap - 1 - len(b)))
