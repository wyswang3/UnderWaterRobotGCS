from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class GuiConfig:
    """Qt GUI runtime config.

    The GUI shares the same transport/session environment variables as the TUI so
    operators do not need a separate configuration surface in the first stage.
    """

    rov_ip: str = "192.168.2.24"
    rov_port: int = 14550

    bind_ip: str = "0.0.0.0"
    bind_port: int = 14551

    poll_hz: int = 50
    heartbeat_hz: int = 2
    handshake_timeout_s: float = 2.0

    refresh_hz: int = 5
    auto_connect: bool = True
    telemetry_source: str = "udp"
    window_title: str = "UnderWaterRobotGCS"

    @staticmethod
    def from_env() -> "GuiConfig":
        cfg = GuiConfig()
        cfg.rov_ip = os.getenv("UROGCS_ROV_IP", cfg.rov_ip)
        cfg.rov_port = int(os.getenv("UROGCS_ROV_PORT", str(cfg.rov_port)))

        cfg.bind_ip = os.getenv("UROGCS_BIND_IP", cfg.bind_ip)
        cfg.bind_port = int(os.getenv("UROGCS_BIND_PORT", str(cfg.bind_port)))

        cfg.poll_hz = int(os.getenv("UROGCS_POLL_HZ", str(cfg.poll_hz)))
        cfg.heartbeat_hz = int(os.getenv("UROGCS_HEARTBEAT_HZ", str(cfg.heartbeat_hz)))
        cfg.handshake_timeout_s = float(
            os.getenv("UROGCS_HANDSHAKE_TIMEOUT_S", str(cfg.handshake_timeout_s))
        )

        cfg.refresh_hz = int(os.getenv("UROGCS_GUI_REFRESH_HZ", str(cfg.refresh_hz)))
        cfg.auto_connect = os.getenv("UROGCS_GUI_AUTOCONNECT", "1") not in {"0", "false", "False"}
        cfg.telemetry_source = os.getenv("UROGCS_GUI_SOURCE", cfg.telemetry_source).strip().lower() or cfg.telemetry_source
        cfg.window_title = os.getenv("UROGCS_GUI_TITLE", cfg.window_title)
        return cfg
