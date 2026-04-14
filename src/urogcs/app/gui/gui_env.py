from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class GuiConfig:
    """Qt GUI runtime config.

    The GUI shares the same transport/session environment variables as the TUI so
    operators do not need a separate configuration surface in the first stage.

    Port note:
      - TUI 默认使用固定 bind_port (14551) 便于防火墙/排障；
      - GUI 作为只读观测面板，默认使用 bind_port=0（临时端口），从而可以与 TUI 同时运行而不抢占端口。
    """

    rov_ip: str = "192.168.2.24"
    rov_port: int = 14550

    bind_ip: str = "0.0.0.0"
    bind_port: int = 0

    poll_hz: int = 50
    heartbeat_hz: int = 2
    handshake_timeout_s: float = 2.0

    refresh_hz: int = 5
    auto_connect: bool = True
    telemetry_source: str = "udp"
    window_title: str = "UnderWaterRobotGCS"
    session_debug: bool = False

    @staticmethod
    def from_env() -> "GuiConfig":
        cfg = GuiConfig()
        cfg.rov_ip = os.getenv("UROGCS_ROV_IP", cfg.rov_ip)
        cfg.rov_port = int(os.getenv("UROGCS_ROV_PORT", str(cfg.rov_port)))

        # GUI 允许单独覆写 bind 配置，避免与 TUI 抢端口。
        cfg.bind_ip = os.getenv("UROGCS_GUI_BIND_IP", os.getenv("UROGCS_BIND_IP", cfg.bind_ip))
        cfg.bind_port = int(
            os.getenv("UROGCS_GUI_BIND_PORT", os.getenv("UROGCS_BIND_PORT", str(cfg.bind_port)))
        )

        cfg.poll_hz = int(os.getenv("UROGCS_POLL_HZ", str(cfg.poll_hz)))
        cfg.heartbeat_hz = int(os.getenv("UROGCS_HEARTBEAT_HZ", str(cfg.heartbeat_hz)))
        cfg.handshake_timeout_s = float(
            os.getenv("UROGCS_HANDSHAKE_TIMEOUT_S", str(cfg.handshake_timeout_s))
        )

        cfg.refresh_hz = int(os.getenv("UROGCS_GUI_REFRESH_HZ", str(cfg.refresh_hz)))
        cfg.auto_connect = os.getenv("UROGCS_GUI_AUTOCONNECT", "1") not in {"0", "false", "False"}
        cfg.telemetry_source = os.getenv("UROGCS_GUI_SOURCE", cfg.telemetry_source).strip().lower() or cfg.telemetry_source
        cfg.window_title = os.getenv("UROGCS_GUI_TITLE", cfg.window_title)
        cfg.session_debug = os.getenv("UROGCS_SESSION_DEBUG", "0") not in {"0", "", "false", "False"}
        return cfg
