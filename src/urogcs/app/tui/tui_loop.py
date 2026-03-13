# src/urogcs/app/tui/tui_loop.py
from __future__ import annotations

"""
tui_loop.py

终端 TUI 主循环：

- 通过 GcsService 与香橙派 / gateway 建立 UDP 会话；
- 使用 KeyboardMapper + tui_keys 将键盘输入映射为 6DOF 连续指令 + 离散动作；
- 转发 ESTOP / ARM / 模式切换 / 油门调整 到 gateway；
- 通过 TuiDashboard 以多行 HUD 形式展示当前状态，避免刷屏。

分层约定：
- 平台与配置：tui_env.py       (TuiConfig / now_ns / period_ns)
- 键盘输入与离散语义：tui_keys.py (create_keyboard / apply_special_keys / DiscreteActions)
- HUD 视图：tui_view.py        (TuiDashboard / TuiStatusSnapshot)
- 通信与状态核心：core.service (GcsService / GcsServiceConfig)
"""

import time

from urogcs.protocol.messages import (
    DofCommand,
    command_status_name,
    health_state_name,
    runtime_nav_state_name,
    wire_mode_name,
)
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
         - poll 接收包（STATUS / ACK 等）；
         - 发送心跳；
         - 读取键盘 → 连续 DOF + 离散动作；
         - 应用简单的急停 + 全局油门（最终安全逻辑仍由下位机裁决）；
         - 下发 SET_DOF；
         - 刷新 HUD 仪表盘。
    """

    # ----------------------------
    # 1. 会话 & 状态回调
    # ----------------------------
    last_log_line = ""        # 最近一条日志文本

    def on_status(_st):
        return None

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

    last_arm_log_ns = 0  # 未解锁提醒限流

    # 键盘错误日志限流（避免刷屏）
    last_kb_error_msg = ""
    last_kb_error_ns = 0
    kb_error_suppressed = 0

    # 为“按键集合变化”打印做一个本地快照
    last_keys_snapshot = set()

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
                    svc.request_arm(True, ack_req=True)
                    on_log("[KB] Arm requested (sent to gateway)")

                if actions.disarm:
                    svc.request_arm(False, ack_req=True)
                    on_log("[KB] Disarm requested (sent to gateway)")

                if actions.center:
                    # 仅清空当前 DOF，不改变 estop 状态
                    raw_cmd = DofCommand()
                    on_log("[KB] DOF centered")

                if actions.help:
                    on_log("[KB] Help requested (TUI help not implemented yet)")

                # --- 5.3.5 全局油门调整 ---
                if actions.throttle_delta != 0.0:
                    old_thr = throttle
                    throttle = max(0.0, min(1.01, throttle + actions.throttle_delta))
                    if abs(throttle - old_thr) > 1e-3:
                        on_log(f"[KB] throttle changed -> {throttle:.2f}")

                # --- 5.3.6 连续 DOF 更新 + 键盘变化日志 ---
                if keys != last_keys_snapshot and keys:
                    # 只在按键集合发生变化且非空时打印一次，避免刷屏
                    on_log(f"[KB] keys={''.join(sorted(keys))}")
                    last_keys_snapshot = set(keys)

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
                if throttle < 1.1:
                    cmd_to_send = DofCommand(
                        surge=cmd_to_send.surge * throttle,
                        sway=cmd_to_send.sway * throttle,
                        heave=cmd_to_send.heave * throttle,
                        roll=cmd_to_send.roll * throttle,
                        pitch=cmd_to_send.pitch * throttle,
                        yaw=cmd_to_send.yaw * throttle,
                    )

                # 5.5 下发 DOF 命令（始终下发，由下位机根据 ARM/ESTOP 决定是否“接受”）
                if now >= next_send_ns:
                    while now >= next_send_ns:
                        next_send_ns += send_period_ns

                    # 若本地认为未 ARM，则低频提醒操作者，但仍然把“意图”发下去。
                    if not svc.state.armed and now - last_arm_log_ns > 2 * 1_000_000_000:
                        on_log(
                            "[KB] ROV not armed per remote STATUS (press ',' to ARM) "
                            "— DOF may be ignored downstream."
                        )
                        last_arm_log_ns = now

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
                    status_age_ms = None
                    if st.last_status_rx_ns > 0:
                        status_age_ms = (now - st.last_status_rx_ns) / 1_000_000.0

                    ack_code = st.last_ack_code
                    ack_code_str = ""
                    if ack_code is not None:
                        try:
                            from urogcs.protocol.wire import AckCode

                            ack_code_str = AckCode(int(ack_code)).name
                        except Exception:
                            ack_code_str = str(ack_code)

                    snap = TuiStatusSnapshot(
                        local_estop=bool(estop_latched),
                        local_mode=current_mode,
                        throttle=throttle,
                        cmd=raw_cmd,
                        session_established=int(st.session_established),
                        link_alive=int(st.link_alive),
                        status_age_ms=status_age_ms,
                        status_seq=st.status_seq,
                        remote_armed=int(st.armed),
                        remote_estop=int(st.estop),
                        remote_mode=wire_mode_name(st.mode),
                        remote_failsafe=int(st.failsafe_active),
                        active_controller=st.active_controller,
                        desired_controller=st.desired_controller,
                        nav_valid=int(st.nav_valid),
                        nav_state=runtime_nav_state_name(st.nav_state),
                        nav_stale=int(st.nav_stale),
                        nav_degraded=int(st.nav_degraded),
                        health_state=health_state_name(st.health_state),
                        fault_state=int(st.fault_state),
                        last_fault_code=st.last_fault_code,
                        command_status=command_status_name(st.command_status),
                        command_cmd_seq=st.command_cmd_seq,
                        last_tx_kind=st.last_tx_kind,
                        last_tx_seq=st.last_tx_seq,
                        waiting_ack=st.waiting_ack,
                        pending_ack_seq=st.pending_ack_seq,
                        pending_ack_kind=st.pending_ack_kind,
                        last_ack_kind=st.last_ack_kind,
                        last_ack_code=ack_code_str,
                        last_ack_reason=st.last_ack_reason,
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
