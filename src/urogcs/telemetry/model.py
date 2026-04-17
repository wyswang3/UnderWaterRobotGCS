"""Runtime telemetry snapshot model shared by GCS views and alarms.

作用：
- 保存最近一次成功解码的 STATUS 以及对应接收时间；
- 提供 UI/告警层常用的只读派生属性，统一解释 mode/nav/health 等状态。

实现思路：
- 快照层只缓存权威遥测与轻量派生值，不引入新的控制语义；
- TUI、GUI 和 alarm 逻辑都围绕同一个 TelemetrySnapshot 读取，减少状态漂移。
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Optional

from urogcs.protocol.messages import (
    StatusTelemetry,
    command_status_name,
    health_state_name,
    nav_diagnostic_summary,
    nav_fault_name,
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
    def nav_fault_code(self) -> int:
        return int(self.status.nav_fault_code) if self.status else 0

    @property
    def nav_fault_name(self) -> str:
        return nav_fault_name(self.nav_fault_code)

    @property
    def nav_status_flags(self) -> int:
        return int(self.status.nav_status_flags) if self.status else 0

    @property
    def nav_diagnostic_summary(self) -> str:
        if not self.status:
            return "unknown"
        return nav_diagnostic_summary(
            nav_valid=int(self.status.nav_valid),
            nav_stale=int(self.status.nav_stale),
            nav_degraded=int(self.status.nav_degraded),
            nav_fault_code=int(self.status.nav_fault_code),
            nav_status_flags=int(self.status.nav_status_flags),
        )

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
