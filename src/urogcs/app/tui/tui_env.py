# src/urogcs/app/tui_env.py
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass


# =========================
# 平台判定
# =========================

IS_WINDOWS: bool = sys.platform.startswith("win")
IS_POSIX: bool = os.name == "posix"


# =========================
# 配置
# =========================

@dataclass
class TuiConfig:
    """
    TUI 运行配置：
      - ROV/Gateway 地址与端口
      - 本地绑定地址与端口
      - 发送/轮询/心跳/打印频率
      - 握手超时时间
    """
    rov_ip: str = "192.168.2.24"
    rov_port: int = 14550   # 与 gcs_server 默认一致

    bind_ip: str = "0.0.0.0"
    bind_port: int = 14551

    send_hz: int = 20
    poll_hz: int = 50
    heartbeat_hz: int = 2

    handshake_timeout_s: float = 2.0
    print_hz: int = 10
    session_debug: bool = False

    @staticmethod
    def from_env() -> "TuiConfig":
        """
        支持通过环境变量覆写默认配置，便于不同实验环境下调整。
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
        cfg.session_debug = os.getenv("UROGCS_SESSION_DEBUG", "0") not in {"0", "", "false", "False"}
        return cfg


# =========================
# 时间/格式化工具
# =========================

def now_ns() -> int:
    """使用 monotonic_ns 作为控制循环时间基。"""
    return time.monotonic_ns()


def period_ns(hz: int) -> int:
    """将频率转换为纳秒周期。"""
    return int(1_000_000_000 // max(1, hz))


def mode_name(v: int) -> str:
    """将模式枚举值转换为人类可读字符串。"""
    return {0: "Unknown", 1: "Manual", 2: "Auto", 3: "Failsafe"}.get(int(v), "Unknown")
