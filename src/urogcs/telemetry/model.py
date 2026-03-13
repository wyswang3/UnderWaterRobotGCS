# src/urogcs/telemetry/model.py
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Optional

from urogcs.protocol.messages import (
    StatusTelemetry,
    command_status_name,
    health_state_name,
    runtime_nav_state_name,
    wire_mode_name,
)


@dataclass
class TelemetrySnapshot:
    """
    UI / alarms 的统一输入：
    - status: 最近一次解码成功的 StatusTelemetry
    - last_rx_ns: 最近一次收到 STATUS 的本机 monotonic_ns 时间
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
        return wire_mode_name(int(self.status.mode))

    @property
    def link_alive(self) -> bool:
        return bool(self.status.link_alive) if self.status else False

    @property
    def estop(self) -> bool:
        return bool(self.status.estop) if self.status else False

    @property
    def session_established(self) -> bool:
        return bool(self.status.session_established) if self.status else False

    @property
    def armed(self) -> bool:
        return bool(self.status.armed) if self.status else False

    @property
    def failsafe_active(self) -> bool:
        return bool(self.status.failsafe_active) if self.status else False

    @property
    def nav_valid(self) -> bool:
        return bool(self.status.nav_valid) if self.status else False

    @property
    def nav_stale(self) -> bool:
        return bool(self.status.nav_stale) if self.status else False

    @property
    def nav_degraded(self) -> bool:
        return bool(self.status.nav_degraded) if self.status else False

    @property
    def nav_state_str(self) -> str:
        if not self.status:
            return "Unknown"
        return runtime_nav_state_name(int(self.status.nav_state))

    @property
    def health_state_str(self) -> str:
        if not self.status:
            return "Unknown"
        return health_state_name(int(self.status.health_state))

    @property
    def command_status_str(self) -> str:
        if not self.status:
            return "None"
        return command_status_name(int(self.status.command_status))

    def update_status(self, st: StatusTelemetry, *, now_ns: Optional[int] = None) -> None:
        self.status = st
        self.last_rx_ns = int(now_ns if now_ns is not None else time.monotonic_ns())
