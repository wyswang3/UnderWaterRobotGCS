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

    estop: bool
    mode: WireControlMode

    # 可选：全局油门（0..1），现在如果还没接上，可以传 None
    throttle: Optional[float] = None

    # 当前 6DOF 命令
    cmd: Optional[DofCommand] = None

    # gateway/session 状态（可为 None）
    session_established: int = 0
    link_alive: int = 0
    estop_from_remote: int = 0
    mode_from_remote: int = 0
    active_controller: str = ""
    desired_controller: str = ""

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
      [CTL] ...  (模式 / 油门 / 控制器)
      [CMD] ...  (当前 6DOF 命令)
      [NAV] ...  (预留)
      [LOG] ...  (最近一条日志)

    刷新策略：
      - 首次渲染时先打印 panel_height 行空行，分配面板区域；
      - 之后每次渲染用 ANSI 控制码将光标上移 panel_height 行，覆盖重画；
      - 非 ANSI 终端（如某些 Windows 控制台）则退化为普通 print，每次多输出一组 5 行。
    """

    def __init__(self, panel_height: int = 5) -> None:
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
        estop_int = 1 if snap.estop else 0
        mode_str = snap.mode.name if hasattr(snap.mode, "name") else mode_name(int(snap.mode))

        thr_str = "N/A"
        if snap.throttle is not None:
            thr_str = f"{snap.throttle:.2f}"

        cmd = snap.cmd or DofCommand()
        line1 = (
            f"[ROV] {snap.rov_ip}:{snap.rov_port}  "
            f"bind={snap.bind_ip}:{snap.bind_port}  "
            f"sess={int(snap.session_established)} link={int(snap.link_alive)} "
            f"estop={estop_int}"
        )

        line2 = (
            f"[CTL] mode={mode_str}  thr={thr_str}  "
            f"active={snap.active_controller or '-'} "
            f"desired={snap.desired_controller or '-'}"
        )

        line3 = (
            f"[CMD] surge={cmd.surge:+.2f} sway={cmd.sway:+.2f} "
            f"heave={cmd.heave:+.2f} roll={cmd.roll:+.2f} "
            f"pitch={cmd.pitch:+.2f} yaw={cmd.yaw:+.2f}"
        )

        # 先预留 NAV 区，后续可接入导航/姿态/深度信息
        line4 = "[NAV] (no nav telemetry wired yet)"

        log_text = snap.last_log or ""
        if len(log_text) > 120:
            log_text = log_text[:117] + "..."
        line5 = f"[LOG] {log_text}"

        lines = [line1, line2, line3, line4, line5]

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
