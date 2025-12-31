# src/urogcs/app/tui_main.py
from __future__ import annotations

import os
import sys
import time
import select
from dataclasses import dataclass
from typing import Optional, Set, Tuple

from urogcs.session.session_client import GcsSessionClient

# Payload DTOs/helpers live in messages.py
from urogcs.protocol.messages import DofCommand

# Wire enums/constants live in wire.py (single source of truth)
from urogcs.protocol.wire import WireControlMode

from urogcs.control.safety import SafetyPolicy, SafetyConfig
from urogcs.control.keyboard_mapper import KeyboardMapper


# =========================
# Config
# =========================

@dataclass
class TuiConfig:
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
        cfg = TuiConfig()
        cfg.rov_ip = os.getenv("UROGCS_ROV_IP", cfg.rov_ip)
        cfg.rov_port = int(os.getenv("UROGCS_ROV_PORT", str(cfg.rov_port)))

        cfg.bind_ip = os.getenv("UROGCS_BIND_IP", cfg.bind_ip)
        cfg.bind_port = int(os.getenv("UROGCS_BIND_PORT", str(cfg.bind_port)))

        cfg.send_hz = int(os.getenv("UROGCS_SEND_HZ", str(cfg.send_hz)))
        cfg.poll_hz = int(os.getenv("UROGCS_POLL_HZ", str(cfg.poll_hz)))
        cfg.heartbeat_hz = int(os.getenv("UROGCS_HEARTBEAT_HZ", str(cfg.heartbeat_hz)))

        cfg.handshake_timeout_s = float(os.getenv("UROGCS_HANDSHAKE_TIMEOUT_S", str(cfg.handshake_timeout_s)))
        cfg.print_hz = int(os.getenv("UROGCS_PRINT_HZ", str(cfg.print_hz)))
        return cfg


# =========================
# Time / formatting
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

    - Enables cbreak mode only when stdin is a TTY.
    - Reads raw bytes with select().
    - Returns a set of keys pressed during this tick.
      (Terminal cannot detect key-up; keys are treated as "pressed in this tick".)

    Keys:
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
            return self
        if not sys.stdin.isatty():
            # Running under pipe/IDE etc. Disable keyboard handling safely.
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

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if not self.enabled:
            return
        try:
            import termios
            if self._fd is not None and self._orig is not None:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._orig)
        except Exception:
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
# Keyboard adaptation
# =========================

def _apply_special_keys(keys: Set[str]) -> Tuple[bool, Optional[WireControlMode], bool]:
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
# Main TUI
# =========================

def run_tui(cfg: TuiConfig) -> int:
    last_status = None
    last_log_line = ""

    def on_status(st):
        nonlocal last_status
        last_status = st

    def on_log(s: str):
        nonlocal last_log_line
        last_log_line = s

    cli = GcsSessionClient(
        rov_addr=(cfg.rov_ip, cfg.rov_port),
        bind_addr=(cfg.bind_ip, cfg.bind_port),
        recv_timeout_ms=int(1000 / max(1, cfg.poll_hz)),
        on_status=on_status,
        on_log=on_log,
    )

    safety = SafetyPolicy(SafetyConfig())
    mapper = KeyboardMapper()

    send_period_ns = _period_ns(cfg.send_hz)
    poll_period_ns = _period_ns(cfg.poll_hz)
    hb_period_ns = _period_ns(cfg.heartbeat_hz) if cfg.heartbeat_hz > 0 else 0
    print_period_ns = _period_ns(cfg.print_hz)

    now = _now_ns()
    next_send_ns = now + send_period_ns
    next_poll_ns = now + poll_period_ns
    next_hb_ns = now + hb_period_ns if hb_period_ns else 0
    next_print_ns = now + print_period_ns

    estop_latched = False
    current_mode = WireControlMode.Manual
    raw_cmd = DofCommand()

    print("[TUI] UnderWaterRobotGCS minimal TUI")
    print(f"[TUI] target={cfg.rov_ip}:{cfg.rov_port} bind={cfg.bind_ip}:{cfg.bind_port}")
    print("[TUI] starting handshake...")

    try:
        ok = cli.handshake(timeout_s=cfg.handshake_timeout_s)
        if not ok:
            err = getattr(cli, "last_error", "") or "unknown"
            print(f"[ERR] handshake failed: {err}")
            return 2

        # Avoid assuming internal state layout; best-effort print
        sid = getattr(getattr(cli, "st", None), "session_id", None)
        established = getattr(getattr(cli, "st", None), "established", None)
        print(f"[TUI] handshake OK. session_id={sid} established={established}")
        print("[TUI] running. Ctrl+C to quit.")
        print("      keys: WASD/RF translation, QE yaw, I/K pitch, J/L roll, SPACE estop, ESC quit, 1/2/3 mode")
        print("")

        with _LinuxKeyboard() as kb:
            while True:
                now = _now_ns()

                # 1) RX poll
                if now >= next_poll_ns:
                    while now >= next_poll_ns:
                        next_poll_ns += poll_period_ns
                    cli.poll(max_packets=16)

                # 2) heartbeat
                if hb_period_ns and now >= next_hb_ns:
                    while now >= next_hb_ns:
                        next_hb_ns += hb_period_ns
                    try:
                        cli.send_heartbeat(use_session=True, ack_req=False)
                    except Exception as e:
                        on_log(f"[HB] send failed: {e}")

                # 3) keyboard tick
                keys = kb.read_keys_tick()
                togg_estop, mode_req, quit_req = _apply_special_keys(keys)
                if quit_req:
                    raise KeyboardInterrupt()

                try:
                    raw_cmd = mapper.update(keys)
                except Exception as e:
                    on_log(f"[KB] mapper.update failed: {e}")

                if togg_estop:
                    estop_latched = not estop_latched
                    try:
                        cli.send_estop(estop_latched, ack_req=True)
                    except Exception as e:
                        on_log(f"[TX] ESTOP failed: {e}")

                if mode_req is not None and mode_req != current_mode:
                    current_mode = mode_req
                    try:
                        cli.send_set_mode(current_mode, auto_controller="", ack_req=True)
                    except Exception as e:
                        on_log(f"[TX] SET_MODE failed: {e}")

                # 4) estop forces zero
                if estop_latched:
                    raw_cmd = DofCommand()

                # 5) safety + send DOF
                if now >= next_send_ns:
                    while now >= next_send_ns:
                        next_send_ns += send_period_ns

                    cmd6 = (raw_cmd.surge, raw_cmd.sway, raw_cmd.heave, raw_cmd.roll, raw_cmd.pitch, raw_cmd.yaw)
                    try:
                        cmd6 = safety.sanitize_dof(cmd6)
                        cmd6 = safety.maybe_force_zero_on_link_loss(cmd6)

                        safe_cmd = DofCommand(
                            surge=float(cmd6[0]),
                            sway=float(cmd6[1]),
                            heave=float(cmd6[2]),
                            roll=float(cmd6[3]),
                            pitch=float(cmd6[4]),
                            yaw=float(cmd6[5]),
                        )

                        cli.send_set_dof(safe_cmd, ack_req=False)
                        raw_cmd = safe_cmd
                    except Exception as e:
                        on_log(f"[TX] SET_DOF failed: {e}")

                # 6) print
                if now >= next_print_ns:
                    while now >= next_print_ns:
                        next_print_ns += print_period_ns

                    st_line = ""
                    if last_status is not None:
                        st_line = (
                            f" | STATUS: sess={int(last_status.session_established)} link={int(last_status.link_alive)} "
                            f"estop={int(last_status.estop)} mode={_mode_name(int(last_status.mode))} "
                            f"active={last_status.active_controller} desired={last_status.desired_controller}"
                        )
                    log_line = f" | {last_log_line}" if last_log_line else ""
                    print(f"[CMD] estop={int(estop_latched)} mode={current_mode.name} {_fmt_dof(raw_cmd)}{st_line}{log_line}")

                # 7) sleep until next deadline (cap to keep responsive)
                next_deadline = min(next_send_ns, next_poll_ns, next_print_ns)
                if hb_period_ns:
                    next_deadline = min(next_deadline, next_hb_ns)

                now2 = _now_ns()
                sleep_ns = next_deadline - now2
                if sleep_ns > 0:
                    time.sleep(min(sleep_ns / 1e9, 0.02))

    except KeyboardInterrupt:
        print("\n[TUI] stopped by user.")
        return 0
    finally:
        try:
            cli.close()
        except Exception:
            pass


def main() -> int:
    cfg = TuiConfig.from_env()
    return run_tui(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
