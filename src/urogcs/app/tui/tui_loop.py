# src/urogcs/app/tui/tui_loop.py
from __future__ import annotations

"""
tui_loop.py

终端 TUI 主循环：

- 负责与香橙派 / gateway 的 UDP 会话（通过 GcsService 封装 GcsSessionClient）；
- 负责本地键盘控制（WASD/QE/HG/RT/FV → 6DOF）；
- 负责离散命令（急停、模式切换、油门调整等）的分发；
- 通过 TuiDashboard 以多行 HUD 形式展示当前状态，避免刷屏。

分层约定：
- 平台与配置：tui_env.py       (TuiConfig / now_ns / period_ns)
- 键盘输入与离散语义：tui_keys.py (create_keyboard / apply_special_keys / DiscreteActions)
- HUD 视图：tui_view.py        (TuiDashboard / TuiStatusSnapshot)
- 通信与状态核心：core.service (GcsService / GcsServiceConfig)
"""

import time
from typing import Optional

from urogcs.protocol.messages import DofCommand
from urogcs.protocol.wire import WireControlMode
from urogcs.control.keyboard_mapper import KeyboardMapper

from urogcs.core.service import GcsService, GcsServiceConfig

from .tui_env import TuiConfig, now_ns, period_ns
from .tui_keys import create_keyboard, apply_special_keys, DiscreteActions
from .tui_view import TuiDashboard, TuiStatusSnapshot


def run_tui(cfg: TuiConfig) -> int:
    """
    终端 TUI 主循环入口。

    流程：
      1) 创建 GcsService（内部封装 GcsSessionClient），完成握手；
      2) 创建 KeyboardMapper + Keyboard（Linux / Dummy）；
      3) 在固定周期内：
         - poll 接收包；
         - 发送心跳；
         - 读取键盘 → 连续 DOF + 离散动作；
         - 应用简单的急停 + 全局油门（所有安全逻辑仍由下位机最终裁决）；
         - 发送 SET_DOF；
         - 刷新 HUD 仪表盘。
    """
    # ----------------------------
    # 1. 会话 & 状态回调
    # ----------------------------
    last_status = None        # gateway Telemetry 状态（可能为 None）
    last_log_line = ""        # 最近一条日志文本

    def on_status(st):
        nonlocal last_status
        last_status = st

    def on_log(msg: str):
        nonlocal last_log_line
        last_log_line = msg

    svc_cfg = GcsServiceConfig(
        rov_ip=cfg.rov_ip,
        rov_port=cfg.rov_port,
        bind_ip=cfg.bind_ip,
        bind_port=cfg.bind_port,
        poll_hz=cfg.poll_hz,
        heartbeat_hz=cfg.heartbeat_hz,
        handshake_timeout_s=cfg.handshake_timeout_s,
    )
    svc = GcsService(svc_cfg, on_status=on_status, on_log=on_log)

    mapper = KeyboardMapper()
    dashboard = TuiDashboard()

    # ----------------------------
    # 2. 时间调度配置
    # ----------------------------
    send_period_ns = period_ns(cfg.send_hz)
    poll_period_ns = period_ns(cfg.poll_hz)
    hb_period_ns = period_ns(cfg.heartbeat_hz) if cfg.heartbeat_hz > 0 else 0
    print_period_ns = period_ns(cfg.print_hz)

    now = now_ns()
    next_send_ns = now + send_period_ns
    next_poll_ns = now + poll_period_ns
    next_hb_ns = now + hb_period_ns if hb_period_ns else 0
    next_print_ns = now + print_period_ns

    # ----------------------------
    # 3. 控制状态（上位机视角）
    # ----------------------------
    estop_latched = False
    throttle = 1.0  # 全局油门（0..1）
    current_mode = WireControlMode.Manual
    raw_cmd = DofCommand()

    # 键盘错误日志限流（避免刷屏）
    last_kb_error_msg = ""
    last_kb_error_ns = 0
    kb_error_suppressed = 0

    # ----------------------------
    # 4. 启动 / 握手
    # ----------------------------
    print("[TUI] UnderWaterRobotGCS TUI")
    print(f"[TUI] target={cfg.rov_ip}:{cfg.rov_port} bind={cfg.bind_ip}:{cfg.bind_port}")
    print("[TUI] starting handshake...")

    try:
        ok = svc.start()
        if not ok:
            err = svc.last_error or "unknown"
            print(f"[ERR] handshake failed: {err}")
            return 2

        st = svc.state
        print(f"[TUI] handshake OK. session_id={st.session_id} established={st.session_established}")
        print("[TUI] running. Ctrl+C / ESC to quit.")
        print("      Continuous DOF: W/S/A/D/Q/E/H/G/R/T/F/V")
        print("      Discrete keys : SPACE (E-STOP toggle), m (clear estop+center), "
              ", / '，'(Arm), . / '。'(Disarm), -/_ & =/+ (throttle), 1/2/3 (mode)")
        print("")

        kb = create_keyboard()
        with kb:
            # ----------------------------
            # 5. 主循环
            # ----------------------------
            while True:
                now = now_ns()

                # 5.1 接收包轮询
                if now >= next_poll_ns:
                    while now >= next_poll_ns:
                        next_poll_ns += poll_period_ns
                    svc.poll(max_packets=16)

                # 5.2 心跳
                if hb_period_ns and now >= next_hb_ns:
                    while now >= next_hb_ns:
                        next_hb_ns += hb_period_ns
                    svc.send_heartbeat(use_session=True, ack_req=False)

                # 5.3 键盘输入：离散命令 + 连续 DOF
                keys = kb.read_keys_tick()
                actions: DiscreteActions = apply_special_keys(keys)

                # --- 5.3.1 退出 ---
                if actions.exit:
                    raise KeyboardInterrupt()

                # --- 5.3.2 模式切换 ---
                if actions.mode_req is not None and actions.mode_req != current_mode:
                    current_mode = actions.mode_req
                    svc.request_mode(current_mode, auto_controller="", ack_req=True)
                    on_log(f"[KB] mode changed -> {current_mode.name}")

                # --- 5.3.3 急停 / 清除急停 ---
                if actions.togg_estop:
                    estop_latched = not estop_latched
                    svc.request_estop(estop_latched, ack_req=True)
                    on_log(f"[KB] E-STOP toggled -> {int(estop_latched)}")

                if actions.clear_estop:
                    if estop_latched:
                        estop_latched = False
                        svc.request_estop(False, ack_req=True)
                        on_log("[KB] Clear ESTOP requested")

                # --- 5.3.4 Arm / Disarm / Center / Help ---
                if actions.arm:
                    # 目前协议侧暂未定义 Arm 命令，这里先打日志占位
                    on_log("[KB] Arm requested (not wired to protocol yet)")

                if actions.disarm:
                    on_log("[KB] Disarm requested (not wired to protocol yet)")

                if actions.center:
                    # 仅清空当前 DOF，不改变 estop 状态
                    raw_cmd = DofCommand()
                    on_log("[KB] DOF centered")

                if actions.help:
                    on_log("[KB] Help requested (TUI help not implemented yet)")

                # --- 5.3.5 全局油门调整 ---
                if actions.throttle_delta != 0.0:
                    old_thr = throttle
                    throttle = max(0.0, min(1.0, throttle + actions.throttle_delta))
                    if abs(throttle - old_thr) > 1e-3:
                        on_log(f"[KB] throttle changed -> {throttle:.2f}")

                # --- 5.3.6 连续 DOF 更新 ---
                # 每 tick 都调用 update（即使 keys 为空），以便实现“松手衰减”效果。
                if not hasattr(run_tui, "_last_keys"):
                    run_tui._last_keys = set()  # type: ignore[attr-defined]

                last_keys_snapshot = run_tui._last_keys  # type: ignore[attr-defined]
                if keys != last_keys_snapshot and keys:
                    # 只在按键集合发生变化且非空时打印一次，避免刷屏。
                    on_log(f"[KB] keys={''.join(sorted(keys))}")
                    run_tui._last_keys = set(keys)  # type: ignore[attr-defined]

                try:
                    raw_cmd = mapper.update(keys)
                except Exception as e:
                    # 键盘映射错误限流，避免刷屏
                    err_s = str(e)
                    if (err_s != last_kb_error_msg) or (now - last_kb_error_ns > 2 * 1_000_000_000):
                        if kb_error_suppressed > 0:
                            on_log(f"[KB] mapper.update had {kb_error_suppressed} suppressed errors")
                        on_log(f"[KB] mapper.update failed: {err_s}")
                        last_kb_error_msg = err_s
                        last_kb_error_ns = now
                        kb_error_suppressed = 0
                    else:
                        kb_error_suppressed += 1
                    # 发生错误时保持原有命令不变

                # 5.4 急停强制零输出（上位机视角）
                cmd_to_send = raw_cmd
                if estop_latched:
                    cmd_to_send = DofCommand()

                # 应用全局油门缩放（由上位机表达“意图”，下位机仍可再限幅）
                if throttle < 1.0:
                    cmd_to_send = DofCommand(
                        surge=cmd_to_send.surge * throttle,
                        sway=cmd_to_send.sway * throttle,
                        heave=cmd_to_send.heave * throttle,
                        roll=cmd_to_send.roll * throttle,
                        pitch=cmd_to_send.pitch * throttle,
                        yaw=cmd_to_send.yaw * throttle,
                    )

                # 5.5 下发 DOF 命令
                if now >= next_send_ns:
                    while now >= next_send_ns:
                        next_send_ns += send_period_ns

                    on_log(
                        "[TX] SET_DOF "
                        f"s={cmd_to_send.surge:+.2f} "
                        f"sw={cmd_to_send.sway:+.2f} "
                        f"h={cmd_to_send.heave:+.2f} "
                        f"r={cmd_to_send.roll:+.2f} "
                        f"p={cmd_to_send.pitch:+.2f} "
                        f"y={cmd_to_send.yaw:+.2f}"
                    )

                    svc.send_dof(cmd_to_send, ack_req=False)
                    raw_cmd = cmd_to_send  # HUD 显示的是“已发送”的命令

                # 5.6 HUD 刷新
                if now >= next_print_ns:
                    while now >= next_print_ns:
                        next_print_ns += print_period_ns

                    # 从 GcsServiceState + Telemetry 中提取关键信息
                    st = svc.state

                    sess_est = int(st.session_established)
                    link_alive = int(st.link_alive)
                    remote_estop = int(getattr(last_status, "estop", 0)) if last_status is not None else 0
                    remote_mode = int(getattr(last_status, "mode", 0)) if last_status is not None else 0
                    active_ctl = st.active_controller
                    desired_ctl = st.desired_controller

                    snap = TuiStatusSnapshot(
                        estop=bool(estop_latched),
                        mode=current_mode,
                        throttle=throttle,
                        cmd=raw_cmd,
                        session_established=sess_est,
                        link_alive=link_alive,
                        estop_from_remote=remote_estop,
                        mode_from_remote=remote_mode,
                        active_controller=active_ctl,
                        desired_controller=desired_ctl,
                        rov_ip=cfg.rov_ip,
                        rov_port=cfg.rov_port,
                        bind_ip=cfg.bind_ip,
                        bind_port=cfg.bind_port,
                        last_log=last_log_line,
                    )

                    dashboard.render(snap)

                # 5.7 睡眠直到下一个调度点（保持 CPU 友好）
                next_deadline = min(next_send_ns, next_poll_ns, next_print_ns)
                if hb_period_ns:
                    next_deadline = min(next_deadline, next_hb_ns)

                now2 = now_ns()
                sleep_ns = next_deadline - now2
                if sleep_ns > 0:
                    time.sleep(min(sleep_ns / 1e9, 0.02))

    except KeyboardInterrupt:
        print("\n[TUI] stopped by user.")
        return 0
    finally:
        try:
            svc.close()
        except Exception:
            pass
