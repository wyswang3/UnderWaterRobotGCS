# src/urogcs/app/tui/tui_view.py
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional

from urogcs.protocol.messages import DofCommand
from urogcs.protocol.wire import WireControlMode

from urogcs.app.tui.tui_env import mode_name


_IS_ANSI_TERMINAL = os.name == "posix" and sys.stdout.isatty()
_LINK_STALE_MS = 600.0


@dataclass
class TuiStatusSnapshot:
    """供 HUD 渲染使用的一份状态快照。"""

    local_estop: bool
    local_mode: WireControlMode

    # 可选：全局油门（0..1），现在如果还没接上，可以传 None
    throttle: Optional[float] = None

    # 当前 6DOF 命令
    cmd: Optional[DofCommand] = None

    # gateway/session 状态（可为 None）
    session_established: int = 0
    link_alive: int = 0
    status_age_ms: Optional[float] = None
    status_seq: int = 0

    remote_armed: int = 0
    remote_estop: int = 0
    remote_mode: str = "Unknown"
    remote_failsafe: int = 0
    active_controller: str = ""
    desired_controller: str = ""

    nav_valid: int = 0
    nav_state: str = "Unknown"
    nav_stale: int = 0
    nav_degraded: int = 0
    nav_fault_name: str = "None"
    nav_diag_summary: str = "unknown"
    imu_online: int = 0
    dvl_online: int = 0
    imu_reconnecting: int = 0
    dvl_reconnecting: int = 0
    imu_mismatch: int = 0
    dvl_mismatch: int = 0
    health_state: str = "Unknown"
    fault_state: int = 0
    last_fault_code: int = 0

    command_status: str = "None"
    command_fault_code: int = 0
    command_cmd_seq: int = 0
    last_tx_kind: str = ""
    last_tx_seq: Optional[int] = None
    waiting_ack: bool = False
    pending_ack_seq: Optional[int] = None
    pending_ack_kind: str = ""
    last_ack_kind: str = ""
    last_ack_code: str = ""
    last_ack_reason: Optional[int] = None

    # 网络配置（只在第一行展示）
    rov_ip: str = "?"
    rov_port: int = 0
    bind_ip: str = "?"
    bind_port: int = 0

    # 最近一条日志
    last_log: str = ""


def _local_mode_name(local_mode: WireControlMode) -> str:
    if hasattr(local_mode, "name"):
        return local_mode.name
    return mode_name(int(local_mode))


def _connection_state(snap: TuiStatusSnapshot) -> str:
    if snap.status_age_ms is None:
        return "waiting_status" if snap.session_established else "disconnected"
    if not snap.session_established:
        return "handshaking"
    if (not snap.link_alive) or (snap.status_age_ms >= _LINK_STALE_MS):
        return "stale"
    return "connected"


def _device_state(*, online: int, reconnecting: int, mismatch: int) -> str:
    if mismatch:
        return "mismatch"
    if reconnecting:
        return "reconnecting"
    if online:
        return "online"
    return "device_offline"


def _overall_device_state(imu_state: str, dvl_state: str) -> str:
    states = {imu_state, dvl_state}
    if "mismatch" in states:
        return "mismatch"
    if "reconnecting" in states:
        return "reconnecting"
    if "device_offline" in states:
        return "device_offline"
    if states == {"online"}:
        return "online"
    return "unknown"


def _nav_state_label(snap: TuiStatusSnapshot) -> str:
    if snap.nav_stale:
        return "stale"
    if not snap.nav_valid:
        return "invalid"
    if snap.nav_degraded:
        return "degraded"
    return "ok"


def _control_state_label(snap: TuiStatusSnapshot) -> str:
    if snap.remote_estop:
        return "estop"
    if snap.remote_failsafe:
        return "failsafe"
    if not snap.remote_armed:
        return "disarmed"
    if snap.remote_mode == "Auto":
        return "auto_ready"
    if snap.remote_mode == "Manual":
        return "manual_ready"
    return f"{(snap.remote_mode or 'unknown').lower()}_ready"


def _command_runtime_state(snap: TuiStatusSnapshot) -> str:
    runtime = (snap.command_status or "None").strip()
    if not runtime or runtime == "None":
        return "none"
    return runtime.lower()


def _command_transport_state(snap: TuiStatusSnapshot) -> str:
    if snap.waiting_ack and snap.pending_ack_seq is not None:
        return "pending_ack"
    if snap.last_ack_code:
        if snap.last_ack_code == "OK":
            return "acknowledged"
        return f"ack_error({snap.last_ack_code.lower()})"
    if snap.last_tx_seq is not None:
        return "sent"
    return "idle"


def _command_lifecycle(snap: TuiStatusSnapshot) -> str:
    parts = []
    if snap.last_tx_seq is not None:
        parts.append("sent")

    transport = _command_transport_state(snap)
    if transport == "pending_ack":
        parts.append("pending_ack")
    elif transport == "acknowledged":
        parts.append("acknowledged")
    elif transport.startswith("ack_error("):
        parts.append("ack_error")

    runtime = _command_runtime_state(snap)
    if runtime != "none":
        parts.append(runtime)

    if not parts:
        return "idle"

    deduped = []
    for item in parts:
        if not deduped or deduped[-1] != item:
            deduped.append(item)
    return ">".join(deduped)


def _command_fault_value(snap: TuiStatusSnapshot) -> int:
    if snap.command_fault_code:
        return int(snap.command_fault_code)
    return int(snap.last_fault_code)


def _guidance(snap: TuiStatusSnapshot, local_mode_str: str) -> tuple[str, str]:
    conn_state = _connection_state(snap)
    imu_state = _device_state(
        online=snap.imu_online,
        reconnecting=snap.imu_reconnecting,
        mismatch=snap.imu_mismatch,
    )
    dvl_state = _device_state(
        online=snap.dvl_online,
        reconnecting=snap.dvl_reconnecting,
        mismatch=snap.dvl_mismatch,
    )
    runtime = _command_runtime_state(snap)

    # 只提示“当前最阻断操作的一件事”，避免客户在多个异常里迷路。
    if conn_state == "disconnected":
        return (
            "vehicle_not_connected",
            "check ROV IP, UDP ports and start gcs_server before reopening TUI; export GCS log if handshake still fails",
        )
    if conn_state == "handshaking":
        return (
            "session_handshaking",
            "wait for CONNECT_ACK/CONFIRM; if it stalls, check firewall, target IP and gcs_server",
        )
    if conn_state == "waiting_status":
        return (
            "status_missing",
            "handshake may be up but STATUS is missing; check pwm_control_program telemetry output",
        )
    if conn_state == "stale":
        return (
            "telemetry_stale",
            "check network path and gcs_server/pwm_control_program freshness; export telemetry timeline and GCS log",
        )

    if imu_state == "mismatch":
        return (
            "imu_mismatch",
            "verify IMU USB binding and expected identity; export nav_timing.bin and latest telemetry",
        )
    if dvl_state == "mismatch":
        return (
            "dvl_mismatch",
            "verify DVL USB binding and expected identity; export nav_timing.bin and latest telemetry",
        )
    if imu_state == "reconnecting":
        return (
            "imu_reconnecting",
            "wait for IMU reconnect; if it lasts >5s, reseat USB/power and export nav_timing.bin",
        )
    if dvl_state == "reconnecting":
        return (
            "dvl_reconnecting",
            "wait for DVL reconnect; if it lasts >5s, reseat USB/power and export nav_timing.bin",
        )
    if imu_state == "device_offline":
        return (
            "imu_offline",
            "check IMU power/cable/USB presence; export nav_timing.bin and latest telemetry",
        )
    if dvl_state == "device_offline":
        return (
            "dvl_offline",
            "check DVL power/cable/USB presence; export nav_timing.bin and latest telemetry",
        )

    if snap.remote_estop:
        return (
            "estop_active",
            "clear estop only after confirming surroundings are safe and the remote chain is healthy",
        )
    if snap.remote_failsafe:
        return (
            "failsafe_active",
            "inspect nav/link/guard state before retrying commands; export telemetry and GCS log",
        )
    if (local_mode_str != snap.remote_mode) and (runtime in {"rejected", "expired", "failed"}):
        return (
            "mode_switch_failed",
            "stay in the remote-reported mode; check estop, arm and nav trust preconditions, then export telemetry",
        )
    if snap.nav_stale:
        return (
            "nav_stale",
            "do not enter Auto; check navd/nav_viewd freshness and export nav_timing.bin plus timeline",
        )
    if not snap.nav_valid:
        return (
            "nav_invalid",
            "keep Manual/Failsafe; inspect nav fault or alignment state, then export nav_timing.bin",
        )
    if runtime in {"rejected", "expired", "failed"}:
        return (
            "command_failed",
            "check fault code and current mode/arm preconditions; export telemetry and GCS log",
        )

    return (
        "ready",
        "link and telemetry look usable; follow clear_estop -> arm -> command order",
    )


class TuiDashboard:
    """
    多行仪表盘 HUD：

      [ROV ] ...  (目标地址与绑定地址)
      [CONN] ...  (连接/会话状态)
      [DEV ] ...  (设备在线/重连/错绑)
      [NAV ] ...  (导航可信度与故障摘要)
      [CTRL] ...  (本地/远端控制状态)
      [CMD ] ...  (sent / acknowledged / runtime 结果)
      [HINT] ...  (客户下一步动作)
      [SAFE] ...  (单键 teleop 安全提示)
      [DOF ] ...  (当前 6DOF 命令)
      [LOG ] ...  (最近一条日志)

    刷新策略：
      - 首次渲染时先打印 panel_height 行空行，分配面板区域；
      - 之后每次渲染用 ANSI 控制码将光标上移 panel_height 行，覆盖重画；
      - 非 ANSI 终端（如某些 Windows 控制台）则退化为普通 print，每次多输出一组状态块。
    """

    def __init__(self, panel_height: int = 10) -> None:
        self.panel_height = panel_height
        self.initialized = False
        self._last_width = 0

    def _ensure_panel(self) -> None:
        if self.initialized:
            return
        if _IS_ANSI_TERMINAL:
            # 先“占位”几行，这样后续可以回到这里覆盖
            sys.stdout.write("\n" * self.panel_height)
            sys.stdout.flush()
        self.initialized = True

    def render(self, snap: TuiStatusSnapshot) -> None:
        self._ensure_panel()

        local_mode_str = _local_mode_name(snap.local_mode)
        estop_int = 1 if snap.local_estop else 0

        thr_str = "N/A"
        if snap.throttle is not None:
            thr_str = f"{snap.throttle:.2f}"

        age_str = "?"
        if snap.status_age_ms is not None:
            age_str = f"{snap.status_age_ms:.0f}ms"

        cmd = snap.cmd or DofCommand()
        conn_state = _connection_state(snap)
        imu_state = _device_state(
            online=snap.imu_online,
            reconnecting=snap.imu_reconnecting,
            mismatch=snap.imu_mismatch,
        )
        dvl_state = _device_state(
            online=snap.dvl_online,
            reconnecting=snap.dvl_reconnecting,
            mismatch=snap.dvl_mismatch,
        )
        device_state = _overall_device_state(imu_state, dvl_state)
        nav_state = _nav_state_label(snap)
        control_state = _control_state_label(snap)
        transport_state = _command_transport_state(snap)
        runtime_state = _command_runtime_state(snap)
        lifecycle = _command_lifecycle(snap)
        blocked_reason, next_action = _guidance(snap, local_mode_str)

        sent = "-"
        if snap.last_tx_seq is not None:
            sent = f"{snap.last_tx_kind or 'CMD'}#{snap.last_tx_seq}"

        ack = "none"
        if snap.waiting_ack and snap.pending_ack_seq is not None:
            ack = f"pending {snap.pending_ack_kind or 'ACK'}#{snap.pending_ack_seq}"
        elif snap.last_ack_code:
            ack = snap.last_ack_code.lower()
            if snap.last_ack_reason is not None:
                ack = f"{ack}/{snap.last_ack_reason}"

        line1 = (
            f"[ROV ] target={snap.rov_ip}:{snap.rov_port}  "
            f"bind={snap.bind_ip}:{snap.bind_port}"
        )

        line2 = (
            f"[CONN] state={conn_state} sess={int(snap.session_established)} "
            f"link={int(snap.link_alive)} age={age_str} seq={snap.status_seq}"
        )

        line3 = (
            f"[DEV ] overall={device_state} imu={imu_state} dvl={dvl_state}"
        )

        line4 = (
            f"[NAV ] state={nav_state} reported={snap.nav_state} valid={int(snap.nav_valid)} "
            f"health={snap.health_state} nav_fault={snap.nav_fault_name} diag={snap.nav_diag_summary}"
        )

        line5 = (
            f"[CTRL] state={control_state} local_mode={local_mode_str} remote_mode={snap.remote_mode} "
            f"local_estop={estop_int} armed={int(snap.remote_armed)} estop={int(snap.remote_estop)} "
            f"failsafe={int(snap.remote_failsafe)} thr={thr_str} ctl={snap.active_controller or '-'}->{snap.desired_controller or '-'}"
        )

        line6 = (
            f"[CMD ] sent={sent} transport={transport_state} ack={ack} runtime={runtime_state} "
            f"lifecycle={lifecycle} cmd_seq={snap.command_cmd_seq} fault={_command_fault_value(snap)}"
        )

        line7 = f"[HINT] blocked={blocked_reason} next={next_action}"

        line8 = (
            "[SAFE] teleop_motion=single_key_only combo_motion_keys=ignored "
            "reason=kinematics+battery_safety"
        )

        line9 = (
            f"[DOF ] surge={cmd.surge:+.2f} sway={cmd.sway:+.2f} "
            f"heave={cmd.heave:+.2f} roll={cmd.roll:+.2f} "
            f"pitch={cmd.pitch:+.2f} yaw={cmd.yaw:+.2f}"
        )

        log_text = snap.last_log or ""
        if len(log_text) > 120:
            log_text = log_text[:117] + "..."
        line10 = f"[LOG ] {log_text}"

        lines = [line1, line2, line3, line4, line5, line6, line7, line8, line9, line10]

        max_width = max(len(l) for l in lines)
        self._last_width = max(self._last_width, max_width)

        if _IS_ANSI_TERMINAL:
            sys.stdout.write(f"\x1b[{self.panel_height}F")
            for l in lines:
                padded = l.ljust(self._last_width)
                sys.stdout.write(padded + "\n")
            sys.stdout.flush()
        else:
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()
