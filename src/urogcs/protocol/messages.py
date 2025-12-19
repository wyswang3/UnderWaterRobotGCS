# src/urogcs/protocol/messages.py
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List

K_MAGIC = 0x524F5647  # 'ROVG'
K_PROTO_VERSION = 1

K_MAX_PAYLOAD = 1024
K_HEADER_SIZE = 40

K_AUTO_NAME_MAX_LEN = 16
K_CTRL_NAME_MAX_LEN = 16

FLAG_ACK_REQ = 0x0001
FLAG_IS_ACK  = 0x0002


class MsgType(IntEnum):
    CONNECT_REQ     = 1
    CONNECT_ACK     = 2
    CONNECT_CONFIRM = 3

    HEARTBEAT       = 10

    SET_MODE        = 20
    SET_DOF_CMD     = 21
    ESTOP           = 22

    STATUS          = 40

    ACK             = 250


class AckCode(IntEnum):
    OK              = 0
    BAD_FORMAT      = 1
    CRC_FAIL        = 2
    INVALID_SESSION = 3
    SEQ_OLD_OR_DUP  = 4
    NOT_SUPPORTED   = 5


class WireControlMode(IntEnum):
    Unknown  = 0
    Manual   = 1
    Auto     = 2
    Failsafe = 3


@dataclass
class DofCommand:
    surge: float = 0.0
    sway:  float = 0.0
    heave: float = 0.0
    roll:  float = 0.0
    pitch: float = 0.0
    yaw:   float = 0.0

    def as_list6(self) -> List[float]:
        return [self.surge, self.sway, self.heave, self.roll, self.pitch, self.yaw]


@dataclass
class StatusTelemetry:
    session_established: int = 0
    link_alive: int = 0
    estop: int = 0
    mode: int = 0  # WireControlMode numeric
    active_controller: str = ""
    desired_controller: str = ""
    consecutive_failures: int = 0
    auto_fail_limit: int = 0
    t_ns: int = 0


def clamp_cstr(s: str, cap: int) -> bytes:
    # C++ write_cstr: null-terminated, zero padded, max cap-1 bytes content
    b = (s or "").encode("utf-8", errors="ignore")
    b = b[: max(0, cap - 1)]
    return b + b"\x00" + (b"\x00" * (cap - 1 - len(b)))
