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
    health_state: str = "Unknown"
    fault_state: int = 0
    last_fault_code: int = 0

    command_status: str = "None"
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


class TuiDashboard:
    """
    多行仪表盘 HUD：

      [ROV] ...  (连接与会话)
      [OP ] ...  (本地操作员意图)
      [AUTH] ... (远端权威运行态)
      [NAV] ...  (导航可信度)
      [CMD] ...  (命令发送 / ACK / 运行态结果)
      [DOF] ...  (当前 6DOF 命令)
      [LOG] ...  (最近一条日志)

    刷新策略：
      - 首次渲染时先打印 panel_height 行空行，分配面板区域；
      - 之后每次渲染用 ANSI 控制码将光标上移 panel_height 行，覆盖重画；
      - 非 ANSI 终端（如某些 Windows 控制台）则退化为普通 print，每次多输出一组 5 行。
    """

    def __init__(self, panel_height: int = 7) -> None:
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

        # 1) 构造 5 行文本
        estop_int = 1 if snap.local_estop else 0
        mode_str = (
            snap.local_mode.name
            if hasattr(snap.local_mode, "name")
            else mode_name(int(snap.local_mode))
        )

        thr_str = "N/A"
        if snap.throttle is not None:
            thr_str = f"{snap.throttle:.2f}"

        age_str = "?"
        if snap.status_age_ms is not None:
            age_str = f"{snap.status_age_ms:.0f}ms"

        cmd = snap.cmd or DofCommand()
        line1 = (
            f"[ROV] {snap.rov_ip}:{snap.rov_port}  "
            f"bind={snap.bind_ip}:{snap.bind_port}  "
            f"sess={int(snap.session_established)} link={int(snap.link_alive)} "
            f"age={age_str} seq={snap.status_seq}"
        )

        line2 = (
            f"[OP ] mode={mode_str} estop={estop_int} thr={thr_str}"
        )

        line3 = (
            f"[AUTH] armed={int(snap.remote_armed)} estop={int(snap.remote_estop)} "
            f"mode={snap.remote_mode} failsafe={int(snap.remote_failsafe)} "
            f"active={snap.active_controller or '-'} desired={snap.desired_controller or '-'}"
        )

        line4 = (
            f"[NAV] valid={int(snap.nav_valid)} state={snap.nav_state} "
            f"stale={int(snap.nav_stale)} degraded={int(snap.nav_degraded)} "
            f"health={snap.health_state} fault={int(snap.fault_state)} "
            f"nav_fault={snap.nav_fault_name} code={snap.last_fault_code} "
            f"diag={snap.nav_diag_summary}"
        )

        sent = "-"
        if snap.last_tx_seq is not None:
            sent = f"{snap.last_tx_kind or 'CMD'}#{snap.last_tx_seq}"

        ack = "idle"
        if snap.waiting_ack and snap.pending_ack_seq is not None:
            ack = f"pending {snap.pending_ack_kind or 'ACK'}#{snap.pending_ack_seq}"
        elif snap.last_ack_code:
            ack = snap.last_ack_code
            if snap.last_ack_reason is not None:
                ack = f"{ack}/{snap.last_ack_reason}"

        line5 = (
            f"[CMD] sent={sent} ack={ack} "
            f"runtime={snap.command_status} cmd_seq={snap.command_cmd_seq}"
        )

        line6 = (
            f"[DOF] surge={cmd.surge:+.2f} sway={cmd.sway:+.2f} "
            f"heave={cmd.heave:+.2f} roll={cmd.roll:+.2f} "
            f"pitch={cmd.pitch:+.2f} yaw={cmd.yaw:+.2f}"
        )

        log_text = snap.last_log or ""
        if len(log_text) > 120:
            log_text = log_text[:117] + "..."
        line7 = f"[LOG] {log_text}"

        lines = [line1, line2, line3, line4, line5, line6, line7]

        # 更新最大宽度，用于右侧填空格，防止残留旧内容
        max_width = max(len(l) for l in lines)
        self._last_width = max(self._last_width, max_width)

        if _IS_ANSI_TERMINAL:
            # 移动光标到面板顶部（上一轮最底行的上方 panel_height 行）
            sys.stdout.write(f"\x1b[{self.panel_height}F")
            # 重画每一行，并用空格填满
            for l in lines:
                padded = l.ljust(self._last_width)
                sys.stdout.write(padded + "\n")
            sys.stdout.flush()
        else:
            # 非 ANSI 终端：退化为简单多行输出（会滚屏，但逻辑简单）
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()
