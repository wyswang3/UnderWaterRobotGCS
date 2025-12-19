# src/urogcs/app/tui_main.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from urogcs.session.session_client import GcsSessionClient
from urogcs.protocol.messages import DofCommand, WireControlMode

from urogcs.control.safety import SafetyPolicy, SafetyConfig
from urogcs.control.keyboard_mapper import KeyboardMapper  # 你已有
# 若你 keyboard_mapper 的 API 与此不同，只需要改动 _read_keyboard() 这一小段


@dataclass
class TuiConfig:
    rov_ip: str = "192.168.2.2"
    rov_port: int = 14550

    # GCS bind：建议固定一个端口便于抓包/防火墙放行
    bind_ip: str = "0.0.0.0"
    bind_port: int = 14551

    # loop
    send_hz: int = 20          # DOF 发送频率（建议 10~30Hz）
    poll_hz: int = 50          # socket poll 频率
    heartbeat_hz: int = 2      # 心跳频率（可选）

    # handshake
    handshake_timeout_s: float = 2.0

    # UI
    print_hz: int = 10         # 控制台刷新频率


def _now_ns() -> int:
    return time.monotonic_ns()


def _fmt_dof(cmd: DofCommand) -> str:
    return (
        f"surge={cmd.surge:+.2f} sway={cmd.sway:+.2f} heave={cmd.heave:+.2f} "
        f"roll={cmd.roll:+.2f} pitch={cmd.pitch:+.2f} yaw={cmd.yaw:+.2f}"
    )


def run_tui(cfg: TuiConfig) -> int:
    # -------- logger / status sink --------
    last_status = {"obj": None}  # store latest StatusTelemetry
    last_log_line = {"s": ""}

    def on_status(st):
        last_status["obj"] = st

    def on_log(s: str):
        last_log_line["s"] = s
        # 你也可以选择打印全部日志；这里默认只保留最后一行，避免刷屏

    # -------- session client --------
    cli = GcsSessionClient(
        rov_addr=(cfg.rov_ip, cfg.rov_port),
        bind_addr=(cfg.bind_ip, cfg.bind_port),
        recv_timeout_ms=int(1000 / max(1, cfg.poll_hz)),
        on_status=on_status,
        on_log=on_log,
    )

    safety = SafetyPolicy(SafetyConfig())
    kb = KeyboardMapper()

    print("[TUI] UnderWaterRobotGCS minimal TUI")
    print(f"[TUI] target={cfg.rov_ip}:{cfg.rov_port} bind={cfg.bind_ip}:{cfg.bind_port}")
    print("[TUI] starting handshake...")

    try:
        if not cli.handshake(timeout_s=cfg.handshake_timeout_s):
            print("[ERR] handshake failed (timeout or nonce mismatch)")
            return 2

        print(f"[TUI] handshake OK. session_id={cli.st.session_id} established={cli.st.established}")
        print("[TUI] running. Ctrl+C to quit.")
        print("")

        send_period_ns = int(1_000_000_000 // max(1, cfg.send_hz))
        poll_period_ns = int(1_000_000_000 // max(1, cfg.poll_hz))
        hb_period_ns = int(1_000_000_000 // max(1, cfg.heartbeat_hz))
        print_period_ns = int(1_000_000_000 // max(1, cfg.print_hz))

        last_send_ns = 0
        last_poll_ns = 0
        last_hb_ns = 0
        last_print_ns = 0

        estop_latched = False
        current_mode = WireControlMode.Manual

        # 初始指令为 0
        raw_cmd = DofCommand()

        while True:
            now = _now_ns()

            # 1) poll RX (STATUS/ACK/...)
            if now - last_poll_ns >= poll_period_ns:
                last_poll_ns = now
                cli.poll(max_packets=16)

            # 2) heartbeat（可选）
            if cfg.heartbeat_hz > 0 and (now - last_hb_ns >= hb_period_ns):
                last_hb_ns = now
                try:
                    # 既可以 use_session=True，也可以 False（server 对 heartbeat 放宽）
                    cli.send_heartbeat(use_session=True, ack_req=False)
                except Exception as e:
                    on_log(f"[HB] send failed: {e}")

            # 3) keyboard -> dof / estop / mode
            raw_cmd, togg_estop, mode_req = _read_keyboard(kb, raw_cmd)

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

            # 4) estop 时强制置零
            if estop_latched:
                raw_cmd = DofCommand()  # all zeros

            # 5) safety + send DOF (high rate, default no ACK)
            if now - last_send_ns >= send_period_ns:
                last_send_ns = now

                # safety.sanitize_dof 需要 tuple[6]，这里做个桥接
                cmd6 = (raw_cmd.surge, raw_cmd.sway, raw_cmd.heave, raw_cmd.roll, raw_cmd.pitch, raw_cmd.yaw)
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

                try:
                    cli.send_set_dof(safe_cmd, ack_req=False)
                except Exception as e:
                    on_log(f"[TX] SET_DOF failed: {e}")

                raw_cmd = safe_cmd

            # 6) print UI periodically
            if now - last_print_ns >= print_period_ns:
                last_print_ns = now
                st = last_status["obj"]
                st_line = ""
                if st is not None:
                    # StatusTelemetry 字段是 int（0/1），mode 是 uint8
                    mode_str = {0: "Unknown", 1: "Manual", 2: "Auto", 3: "Failsafe"}.get(int(st.mode), "Unknown")
                    st_line = (
                        f" | STATUS: sess={int(st.session_established)} link={int(st.link_alive)} "
                        f"estop={int(st.estop)} mode={mode_str} "
                        f"active={st.active_controller} desired={st.desired_controller}"
                    )

                log_line = last_log_line["s"]
                if log_line:
                    log_line = f" | {log_line}"

                print(f"[CMD] estop={int(estop_latched)} mode={current_mode.name} {_fmt_dof(raw_cmd)}{st_line}{log_line}")

            time.sleep(0.002)

    except KeyboardInterrupt:
        print("\n[TUI] stopped by user.")
        return 0
    finally:
        cli.close()


def _read_keyboard(kb: KeyboardMapper, prev_cmd: DofCommand) -> tuple[DofCommand, bool, Optional[WireControlMode]]:
    """
    适配层：把 KeyboardMapper 的输出翻译为：
      - DofCommand
      - togg_estop: bool
      - mode_req: Optional[WireControlMode]

    你现在的 keyboard_mapper.py 我没看到，这里按“最常见设计”做兼容：
      1) kb.poll() -> (dof6, togg_estop, mode_req) 或 (dof6, togg_estop) 或 dof6
      2) dof6 = (surge,sway,heave,roll,pitch,yaw)
    若你的 API 不同，只需要改这一个函数。
    """
    togg_estop = False
    mode_req: Optional[WireControlMode] = None

    r = kb.poll()  # type: ignore

    dof6 = None
    if isinstance(r, tuple) and len(r) == 3:
        dof6, togg_estop, mode_req = r  # type: ignore
    elif isinstance(r, tuple) and len(r) == 2:
        dof6, togg_estop = r  # type: ignore
    else:
        dof6 = r  # type: ignore

    if dof6 is None:
        return prev_cmd, False, None

    # 允许 mapper 返回 list/tuple 长度 6
    try:
        surge, sway, heave, roll, pitch, yaw = [float(x) for x in dof6]
    except Exception:
        # mapper 若返回 DofCommand，也做兼容
        if isinstance(dof6, DofCommand):
            return dof6, bool(togg_estop), mode_req
        return prev_cmd, False, None

    cmd = DofCommand(surge=surge, sway=sway, heave=heave, roll=roll, pitch=pitch, yaw=yaw)
    return cmd, bool(togg_estop), mode_req


def main() -> int:
    cfg = TuiConfig()
    return run_tui(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
