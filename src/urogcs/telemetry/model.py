# src/urogcs/telemetry/model.py
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Optional



from urogcs.protocol.messages import StatusTelemetry, WireControlMode


def mode_to_str(mode_u8: int) -> str:
    """
    Convert wire mode numeric into readable string, aligned with WireControlMode.
    """
    try:
        return WireControlMode(int(mode_u8)).name  # "Manual"/"Auto"/"Failsafe"/"Unknown"
    except Exception:
        return "Unknown"


@dataclass
class TelemetrySnapshot:
    """
    Higher-level telemetry snapshot for UI / alarms.
    This wraps the last received wire-level StatusTelemetry and adds derived fields.
    """
    status: Optional[StatusTelemetry] = None
    last_rx_ns: int = 0

    @property
    def has_status(self) -> bool:
        return self.status is not None

    @property
    def mode_str(self) -> str:
        if not self.status:
            return "Unknown"
        return mode_to_str(int(self.status.mode))

    @property
    def link_alive(self) -> bool:
        return bool(self.status.link_alive) if self.status else False

    @property
    def estop(self) -> bool:
        return bool(self.status.estop) if self.status else False

    @property
    def session_established(self) -> bool:
        return bool(self.status.session_established) if self.status else False
    
class TelemetrySnapshot:
    """
    UI / alarms 的统一输入：
    - status: 最近一次解码成功的 StatusTelemetry
    - last_rx_ns: 最近一次收到 STATUS 的本机 monotonic_ns 时间
    """
    status: Optional[StatusTelemetry] = None
    last_rx_ns: int = 0

    @property
    def mode_str(self) -> str:
        if not self.status:
            return "Unknown"
        return self.status.mode_str

    def update_status(self, st: StatusTelemetry, *, now_ns: Optional[int] = None) -> None:
        self.status = st
        self.last_rx_ns = int(now_ns if now_ns is not None else time.monotonic_ns())
