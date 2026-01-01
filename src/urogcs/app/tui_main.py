# src/urogcs/app/tui_main.py
from __future__ import annotations

import os
import sys
import time
import select
from dataclasses import dataclass
from typing import Callable, Optional, Set, Tuple

from urogcs.session.session_client import GcsSessionClient
from urogcs.protocol.messages import DofCommand
from urogcs.protocol.wire import WireControlMode
from urogcs.control.safety import SafetyPolicy, SafetyConfig

# KeyboardMapper 在某些平台（如 Windows）可能因 termios 等原因导入失败，
# 这里做一次“软依赖”处理，保证上位机至少能跑通通信逻辑。
try:
    from urogcs.control.keyboard_mapper import KeyboardMapper as _KeyboardMapperType
    _KEYBOARD_MAPPER_IMPORT_ERR: Optional[BaseException] = None
except Exception as e:  # noqa: BLE001 - 我们确实要兜底所有异常
    _KeyboardMapperType = None
    _KEYBOARD_MAPPER_IMPORT_ERR = e


# =========================
# Config
# =========================

@dataclass
class TuiConfig:
    """
    上位机 TUI 运行配置（后续做 GUI 时也可以复用这一层配置结构）
    """
    rov_ip: str = "192.168.2.2"
    rov_port: int = 14550   # NOTE: match your server default 14550

    bind_ip: str = "0.0.0.0"
    bind_port: int = 14551

    send_hz: int = 20
    poll_hz: int = 50
    heartbeat_hz: int = 2

    handshake_timeout_s: float = 2.0
    print_hz: int = 10

    @staticmethod
    def from_env() -> "TuiConfig":
        """
        允许通过环境变量覆盖默认配置，便于部署/调参。
        """
        cfg = TuiConfig()
        cfg.rov_ip = os.getenv("UROGCS_ROV_IP", cfg.rov_ip)
        cfg.rov_port = int(os.getenv("UROGCS_ROV_PORT", str(cfg.rov_port)))

        cfg.bind_ip = os.getenv("UROGCS_BIND_IP", cfg.bind_ip)
        cfg.bind_port = int(os.getenv("UROGCS_BIND_PORT", str(cfg.bind_port)))

        cfg.send_hz = int(os.getenv("UROGCS_SEND_HZ", str(cfg.send_hz)))
        cfg.poll_hz = int(os.getenv("UROGCS_POLL_HZ", str(cfg.poll_hz)))
        cfg.heartbeat_hz = int(os.getenv("UROGCS_HEARTBEAT_HZ", str(cfg.heartbeat_hz)))

        cfg.handshake_timeout_s = float(
            os.getenv("UROGCS_HANDSHAKE_TIMEOUT_S", str(cfg.handshake_timeout_s))
        )
        cfg.print_hz = int(os.getenv("UROGCS_PRINT_HZ", str(cfg.print_hz)))
        return cfg


# =========================
# Time / formatting helpers
# =========================

def _now_ns() -> int:
    return time.monotonic_ns()


def _period_ns(hz: int) -> int:
    return int(1_000_000_000 // max(1, hz))


def _fmt_dof(cmd: DofCommand) -> str:
    return (
        f"surge={cmd.surge:+.2f} sway={cmd.sway:+.2f} heave={cmd.heave:+.2f} "
        f"roll={cmd.roll:+.2f} pitch={cmd.pitch:+.2f} yaw={cmd.yaw:+.2f}"
    )


def _mode_name(v: int) -> str:
    return {0: "Unknown", 1: "Manual", 2: "Auto", 3: "Failsafe"}.get(int(v), "Unknown")


# =========================
# Linux non-blocking keyboard
# =========================

class _LinuxKeyboard:
    """
    Minimal, dependency-free, non-blocking keyboard reader for Linux terminals.

    - 仅在 POSIX + TTY 环境启用；
    - 使用 select() + os.read() 读取“本 tick 内按下的键”；
    - 无 key-up 事件概念，键盘视为“该 tick 内被按过”。

    特殊键映射：
      - ESC: quit
      - SPACE: toggle estop
      - 1/2/3: mode manual/auto/failsafe
    """

    def __init__(self) -> None:
        self.enabled = False
        self._orig = None
        self._fd: Optional[int] = None

    def __enter__(self) -> "_LinuxKeyboard":
        if os.name != "posix":
            # 非 POSIX 平台（如 Windows），直接禁用
            return self
        if not sys.stdin.isatty():
            # 非终端环境（IDE/pipe），禁用键盘
            return self

        try:
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._orig = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
            self.enabled = True
        except Exception:
            self.enabled = False
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        self.close()

    def close(self) -> None:
        if not self.enabled:
            return
        try:
            import termios

            if self._fd is not None and self._orig is not None:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._orig)
        except Exception:
            # 恢复失败不致命
            pass
        self.enabled = False

    def read_keys_tick(self, max_bytes: int = 32) -> Set[str]:
        keys: Set[str] = set()
        if not self.enabled or self._fd is None:
            return keys

        r, _, _ = select.select([sys.stdin], [], [], 0.0)
        if not r:
            return keys

        try:
            data = os.read(self._fd, max_bytes)
        except Exception:
            return keys

        for b in data:
            if b == 27:
                keys.add("esc")
            elif b in (10, 13):
                keys.add("enter")
            elif b == 32:
                keys.add("space")
            else:
                ch = chr(b)
                if ch.isprintable():
                    keys.add(ch.lower())
        return keys


# =========================
# Keyboard → control intent helpers
# =========================

def _apply_special_keys(keys: Set[str]) -> Tuple[bool, Optional[WireControlMode], bool]:
    """
    从本 tick 的按键中提取“特殊控制”：
      - togg_estop: 是否切换急停
      - mode_req:   是否请求模式切换
      - quit_req:   是否请求退出程序
    """
    togg_estop = False
    mode_req: Optional[WireControlMode] = None
    quit_req = False

    if "esc" in keys:
        quit_req = True

    if "space" in keys:
        togg_estop = True

    if "1" in keys:
        mode_req = WireControlMode.Manual
    elif "2" in keys:
        mode_req = WireControlMode.Auto
    elif "3" in keys:
        mode_req = WireControlMode.Failsafe

    return togg_estop, mode_req, quit_req


# =========================
# Core TUI app (ready for future UI reuse)
# =========================

class TuiApp:
    """
    TUI 核心应用：

    - 负责握手 / 心跳 / 状态接收；
    - 负责 DOF 命令的节流发送 + 安全策略；
    - 键盘输入只是其中一种“命令来源”，未来可以替换为 GUI / 脚本。
    """

    def __init__(
        self,
        cfg: TuiConfig,
        *,
        on_status: Optional[Callable[[object], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        enable_keyboard: bool = True,
    ) -> None:
        self.cfg = cfg

        self.last_status = None
        self.last_log_line = ""

        def _on_status(st) -> None:
            self.last_status = st
            if on_status is not None:
                on_status(st)

        def _on_log(s: str) -> None:
            self.last_log_line = s
            if on_log is not None:
                on_log(s)

        self.cli = GcsSessionClient(
            rov_addr=(cfg.rov_ip, cfg.rov_port),
            bind_addr=(cfg.bind_ip, cfg.bind_port),
            recv_timeout_ms=int(1000 / max(1, cfg.poll_hz)),
            on_status=_on_status,
            on_log=_on_log,
        )

        self.safety = SafetyPolicy(SafetyConfig())

        # 键盘控制可按平台能力自动降级
        self.mapper = None
        self.keyboard_enabled = enable_keyboard and (os.name == "posix")

        if self.keyboard_enabled and _KeyboardMapperType is not None:
            self.mapper = _KeyboardMapperType()
        elif _KeyboardMapperType is None and enable_keyboard:
            print(
                "[TUI] KeyboardMapper 导入失败，已禁用本地键盘输入，仅保留通信功能："
                f"{_KEYBOARD_MAPPER_IMPORT_ERR}"
            )
        elif not self.keyboard_enabled:
            print("[TUI] 当前平台不支持终端键盘控制，已禁用本地键盘输入，仅保留通信功能。")

        # 运行时状态
        self.estop_latched = False
        self.current_mode = WireControlMode.Manual
        self.raw_cmd = DofCommand()

        # 调度周期（ns）
        self.send_period_ns = _period_ns(cfg.send_hz)
        self.poll_period_ns = _period_ns(cfg.poll_hz)
        self.hb_period_ns = _period_ns(cfg.heartbeat_hz) if cfg.heartbeat_hz > 0 else 0
        self.print_period_ns = _period_ns(cfg.print_hz)

        now = _now_ns()
        self.next_send_ns = now + self.send_period_ns
        self.next_poll_ns = now + self.poll_period_ns
        self.next_hb_ns = now + self.hb_period_ns if self.hb_period_ns else 0
        self.next_print_ns = now + self.print_period_ns

    # -------- handshake --------

    def handshake(self) -> bool:
        print("[TUI] UnderWaterRobotGCS minimal TUI")
        print(f"[TUI] target={self.cfg.rov_ip}:{self.cfg.rov_port} "
              f"bind={self.cfg.bind_ip}:{self.cfg.bind_port}")
        print("[TUI] starting handshake...")

        ok = self.cli.handshake(timeout_s=self.cfg.handshake_timeout_s)
        if not ok:
            err = getattr(self.cli, "last_error", "") or "unknown"
            print(f"[ERR] handshake failed: {err}")
            return False

        sid = getattr(getattr(self.cli, "st", None), "session_id", None)
        established = getattr(getattr(self.cli, "st", None), "established", None)
        print(f"[TUI] handshake OK. session_id={sid} established={established}")
        print("[TUI] running. Ctrl+C to quit.")
        print("      keys: WASD/RF translation, QE yaw, I/K pitch, J/L roll, "
              "SPACE estop, ESC quit, 1/2/3 mode")
        print("")
        return True

    # -------- main loop --------

    def run(self) -> int:
        if not self.handshake():
            return 2

        try:
            # POSIX 下才启用 _LinuxKeyboard；Windows 直接不用键盘，仅跑通信
            kb_ctx: Optional[_LinuxKeyboard] = _LinuxKeyboard() if self.keyboard_enabled else None
            if kb_ctx is not None:
                kb_cm = kb_ctx
            else:
                # dummy context manager
                class _DummyCM:
                    def __enter__(self_inner):
                        return None

                    def __exit__(self_inner, exc_type, exc, tb):
                        return False

                kb_cm = _DummyCM()

            with kb_cm as kb:
                while True:
                    now = _now_ns()

                    # 1) RX poll
                    if now >= self.next_poll_ns:
                        while now >= self.next_poll_ns:
                            self.next_poll_ns += self.poll_period_ns
                        self.cli.poll(max_packets=16)

                    # 2) heartbeat
                    if self.hb_period_ns and now >= self.next_hb_ns:
                        while now >= self.next_hb_ns:
                            self.next_hb_ns += self.hb_period_ns
                        try:
                            self.cli.send_heartbeat(use_session=True, ack_req=False)
                        except Exception as e:
                            self._log(f"[HB] send failed: {e}")

                    # 3) keyboard tick（可能为 None → 无键盘）
                    keys: Set[str] = set()
                    if kb is not None and isinstance(kb, _LinuxKeyboard):
                        keys = kb.read_keys_tick()

                    togg_estop, mode_req, quit_req = _apply_special_keys(keys)
                    if quit_req:
                        raise KeyboardInterrupt()

                    if self.mapper is not None:
                        try:
                            self.raw_cmd = self.mapper.update(keys)
                        except Exception as e:
                            self._log(f"[KB] mapper.update failed: {e}")

                    # 4) ESTOP 控制
                    if togg_estop:
                        self.estop_latched = not self.estop_latched
                        try:
                            self.cli.send_estop(self.estop_latched, ack_req=True)
                        except Exception as e:
                            self._log(f"[TX] ESTOP failed: {e}")

                    if mode_req is not None and mode_req != self.current_mode:
                        self.current_mode = mode_req
                        try:
                            self.cli.send_set_mode(self.current_mode, auto_controller="", ack_req=True)
                        except Exception as e:
                            self._log(f"[TX] SET_MODE failed: {e}")

                    if self.estop_latched:
                        self.raw_cmd = DofCommand()

                    # 5) safety + DOF 发送
                    if now >= self.next_send_ns:
                        while now >= self.next_send_ns:
                            self.next_send_ns += self.send_period_ns

                        cmd6 = (
                            self.raw_cmd.surge,
                            self.raw_cmd.sway,
                            self.raw_cmd.heave,
                            self.raw_cmd.roll,
                            self.raw_cmd.pitch,
                            self.raw_cmd.yaw,
                        )
                        try:
                            cmd6 = self.safety.sanitize_dof(cmd6)
                            cmd6 = self.safety.maybe_force_zero_on_link_loss(cmd6)

                            safe_cmd = DofCommand(
                                surge=float(cmd6[0]),
                                sway=float(cmd6[1]),
                                heave=float(cmd6[2]),
                                roll=float(cmd6[3]),
                                pitch=float(cmd6[4]),
                                yaw=float(cmd6[5]),
                            )

                            self.cli.send_set_dof(safe_cmd, ack_req=False)
                            self.raw_cmd = safe_cmd
                        except Exception as e:
                            self._log(f"[TX] SET_DOF failed: {e}")

                    # 6) 打印状态
                    if now >= self.next_print_ns:
                        while now >= self.next_print_ns:
                            self.next_print_ns += self.print_period_ns

                        st_line = ""
                        if self.last_status is not None:
                            st_line = (
                                f" | STATUS: sess={int(self.last_status.session_established)} "
                                f"link={int(self.last_status.link_alive)} "
                                f"estop={int(self.last_status.estop)} "
                                f"mode={_mode_name(int(self.last_status.mode))} "
                                f"active={self.last_status.active_controller} "
                                f"desired={self.last_status.desired_controller}"
                            )
                        log_line = f" | {self.last_log_line}" if self.last_log_line else ""
                        print(
                            f"[CMD] estop={int(self.estop_latched)} "
                            f"mode={self.current_mode.name} {_fmt_dof(self.raw_cmd)}"
                            f"{st_line}{log_line}"
                        )

                    # 7) 睡眠到下一个最早的 deadline，避免空转
                    next_deadline = min(self.next_send_ns, self.next_poll_ns, self.next_print_ns)
                    if self.hb_period_ns:
                        next_deadline = min(next_deadline, self.next_hb_ns)

                    now2 = _now_ns()
                    sleep_ns = next_deadline - now2
                    if sleep_ns > 0:
                        # 限制最大 sleep，保持响应性
                        time.sleep(min(sleep_ns / 1e9, 0.02))

        except KeyboardInterrupt:
            print("\n[TUI] stopped by user.")
            return 0
        finally:
            try:
                self.cli.close()
            except Exception:
                pass

    # -------- internal helpers --------

    def _log(self, s: str) -> None:
        self.last_log_line = s
        print(s)


# =========================
# Public entrypoints
# =========================

def run_tui(cfg: TuiConfig) -> int:
    """
    供 CLI 调用的简单入口。未来做 GUI 时，可以复用 TuiApp 或拆出无键盘版本。
    """
    app = TuiApp(cfg, enable_keyboard=True)
    return app.run()


def main() -> int:
    cfg = TuiConfig.from_env()
    return run_tui(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
