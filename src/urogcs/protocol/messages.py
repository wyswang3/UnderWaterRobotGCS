"""GCS protocol-side payload and status helper models.

作用：
- 定义 GCS 业务层直接使用的轻量 payload/dataclass；
- 提供把运行时状态码、导航标志和 fault 折叠成稳定 UI 文本的辅助函数。

实现思路：
- 保持这一层只表达 Python 侧业务语义，不重复实现底层 wire 编码；
- 让 TUI/GUI/telemetry 共享同一套状态解释逻辑，避免不同前端各自拼文案。
"""

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


@dataclass
class DvlPolicyCmd:
    enable: int  # 0/1，1=enable DVL policy, 0=disable
    submerged_confirmed: int  # 0/1，1=operator confirmed the DVL is already submerged


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


NAV_FLAG_NONE = 0
NAV_FLAG_IMU_OK = 1 << 0
NAV_FLAG_DVL_OK = 1 << 1
NAV_FLAG_DEPTH_OK = 1 << 2
NAV_FLAG_USBL_OK = 1 << 3
NAV_FLAG_ESKF_OK = 1 << 4
NAV_FLAG_ALIGN_DONE = 1 << 5
NAV_FLAG_IMU_DEVICE_ONLINE = 1 << 6
NAV_FLAG_DVL_DEVICE_ONLINE = 1 << 7
NAV_FLAG_IMU_BIND_MISMATCH = 1 << 8
NAV_FLAG_DVL_BIND_MISMATCH = 1 << 9
NAV_FLAG_IMU_RECONNECTING = 1 << 10
NAV_FLAG_DVL_RECONNECTING = 1 << 11


def nav_fault_name(code: int) -> str:
    return {
        0: "None",
        1: "EstimatorUninitialized",
        2: "AlignmentPending",
        3: "ImuNoData",
        4: "ImuStale",
        5: "DepthStale",
        6: "EstimatorNumericInvalid",
        7: "NavOutputStale",
        8: "NavViewStale",
        9: "NoData",
        10: "ImuDeviceNotFound",
        11: "ImuDeviceMismatch",
        12: "ImuDisconnected",
        13: "DvlDeviceNotFound",
        14: "DvlDeviceMismatch",
        15: "DvlDisconnected",
    }.get(int(code), f"Unknown({int(code)})")


def nav_flag_has(flags: int, flag: int) -> bool:
    return (int(flags) & int(flag)) != 0


def nav_diagnostic_tags(
    *,
    nav_valid: int,
    nav_stale: int,
    nav_degraded: int,
    nav_fault_code: int,
    nav_status_flags: int,
) -> List[str]:
    """Collapse authoritative nav fault/state bits into stable UI filter tags."""
    tags: List[str] = []
    flags = int(nav_status_flags)
    fault_code = int(nav_fault_code)

    if int(nav_stale):
        tags.append("stale")
    if not int(nav_valid):
        tags.append("invalid")
    elif int(nav_degraded):
        tags.append("degraded")

    if nav_flag_has(flags, NAV_FLAG_IMU_BIND_MISMATCH):
        tags.append("imu_mismatch")
    elif nav_flag_has(flags, NAV_FLAG_IMU_RECONNECTING):
        tags.append("imu_reconnecting")
    elif fault_code in (10, 12):
        tags.append("imu_offline")

    if nav_flag_has(flags, NAV_FLAG_DVL_BIND_MISMATCH):
        tags.append("dvl_mismatch")
    elif nav_flag_has(flags, NAV_FLAG_DVL_RECONNECTING):
        tags.append("dvl_reconnecting")
    elif fault_code in (13, 15):
        tags.append("dvl_offline")

    if fault_code not in (0, 10, 11, 12, 13, 14, 15):
        tags.append(nav_fault_name(fault_code))

    if not tags:
        tags.append("ok")
    return tags


def nav_diagnostic_summary(
    *,
    nav_valid: int,
    nav_stale: int,
    nav_degraded: int,
    nav_fault_code: int,
    nav_status_flags: int,
) -> str:
    """Return the compact diagnosis string shown in TUI/UI status rows."""
    tags = nav_diagnostic_tags(
        nav_valid=nav_valid,
        nav_stale=nav_stale,
        nav_degraded=nav_degraded,
        nav_fault_code=nav_fault_code,
        nav_status_flags=nav_status_flags,
    )
    return ",".join(tags)


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
    dvl_policy_enabled: int = 0
    last_fault_code: int = 0
    command_fault_code: int = 0
    nav_fault_code: int = 0
    nav_status_flags: int = 0
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

    @property
    def nav_fault_name(self) -> str:
        return nav_fault_name(self.nav_fault_code)

    @property
    def imu_online(self) -> bool:
        return nav_flag_has(self.nav_status_flags, NAV_FLAG_IMU_DEVICE_ONLINE)

    @property
    def dvl_online(self) -> bool:
        return nav_flag_has(self.nav_status_flags, NAV_FLAG_DVL_DEVICE_ONLINE)

    @property
    def imu_reconnecting(self) -> bool:
        return nav_flag_has(self.nav_status_flags, NAV_FLAG_IMU_RECONNECTING)

    @property
    def dvl_reconnecting(self) -> bool:
        return nav_flag_has(self.nav_status_flags, NAV_FLAG_DVL_RECONNECTING)

    @property
    def imu_mismatch(self) -> bool:
        return nav_flag_has(self.nav_status_flags, NAV_FLAG_IMU_BIND_MISMATCH)

    @property
    def dvl_mismatch(self) -> bool:
        return nav_flag_has(self.nav_status_flags, NAV_FLAG_DVL_BIND_MISMATCH)

    @property
    def nav_diagnostic_summary(self) -> str:
        return nav_diagnostic_summary(
            nav_valid=self.nav_valid,
            nav_stale=self.nav_stale,
            nav_degraded=self.nav_degraded,
            nav_fault_code=self.nav_fault_code,
            nav_status_flags=self.nav_status_flags,
        )

def clamp_cstr(s: str, cap: int) -> bytes:
    b = (s or "").encode("utf-8", errors="ignore")
    b = b[: max(0, cap - 1)]
    return b + b"\x00" + (b"\x00" * (cap - 1 - len(b)))
