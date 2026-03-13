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
class EstopCmd:
    enable: int  # 0/1


@dataclass
class ArmCmd:
    enable: int  # 0/1，1=arm, 0=disarm


def wire_mode_name(mode: int) -> str:
    """Map wire control mode numeric values into stable UI labels."""
    try:
        from urogcs.protocol.wire import WireControlMode

        return WireControlMode(int(mode)).name
    except Exception:
        return "Unknown"


def runtime_nav_state_name(state: int) -> str:
    return {
        0: "Unknown",
        1: "Invalid",
        2: "Degraded",
        3: "Ok",
    }.get(int(state), "Unknown")


def health_state_name(state: int) -> str:
    return {
        0: "Unknown",
        1: "Ok",
        2: "Degraded",
        3: "Fault",
    }.get(int(state), "Unknown")


def command_status_name(code: int) -> str:
    return {
        0: "None",
        1: "Accepted",
        2: "Rejected",
        3: "Executed",
        4: "Expired",
        5: "Failed",
    }.get(int(code), "Unknown")


@dataclass
class StatusTelemetry:
    session_established: int = 0
    link_alive: int = 0
    estop: int = 0
    armed: int = 0
    mode: int = 0
    failsafe_active: int = 0
    nav_valid: int = 0
    nav_state: int = 0
    nav_stale: int = 0
    nav_degraded: int = 0
    fault_state: int = 0
    health_state: int = 0
    command_status: int = 0
    last_fault_code: int = 0
    command_fault_code: int = 0
    active_controller: str = ""
    desired_controller: str = ""
    consecutive_failures: int = 0
    auto_fail_limit: int = 0
    status_seq: int = 0
    command_cmd_seq: int = 0
    t_ns: int = 0

    @property
    def mode_name(self) -> str:
        return wire_mode_name(self.mode)

    @property
    def nav_state_name(self) -> str:
        return runtime_nav_state_name(self.nav_state)

    @property
    def health_state_name(self) -> str:
        return health_state_name(self.health_state)

    @property
    def command_status_name(self) -> str:
        return command_status_name(self.command_status)

def clamp_cstr(s: str, cap: int) -> bytes:
    b = (s or "").encode("utf-8", errors="ignore")
    b = b[: max(0, cap - 1)]
    return b + b"\x00" + (b"\x00" * (cap - 1 - len(b)))
