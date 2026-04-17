# src/urogcs/protocol/wire.py
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, IntFlag
import struct
from typing import Tuple


# =============================================================================
# Protocol constants / version (must match C++)
# =============================================================================

# C++: kMagic = 0x524F5647u  // 'ROVG'
# On wire (little-endian host): bytes appear as 47 56 4F 52 -> "GVOR"
K_MAGIC: int = 0x524F5647
K_PROTO_VERSION: int = 1

K_MAX_PAYLOAD_BYTES: int = 1024

K_AUTO_NAME_MAX_LEN: int = 16
K_CTRL_NAME_MAX_LEN: int = 16




# =============================================================================
# Flags (wire)
# =============================================================================

class Flags(IntFlag):
    ACK_REQ = 0x0001
    IS_ACK  = 0x0002


# =============================================================================
# Wire enums (fixed underlying types)
# =============================================================================

class MsgType(IntEnum):
    # handshake
    CONNECT_REQ     = 1
    CONNECT_ACK     = 2
    CONNECT_CONFIRM = 3

    # heartbeat
    HEARTBEAT       = 10

    # commands (GCS -> ROV)
    SET_MODE        = 20
    SET_DOF_CMD     = 21
    ESTOP           = 22
    ARM             = 23      # ★ 新增：Arm / Disarm
    DVL_POLICY      = 25

    # telemetry (ROV -> GCS)
    STATUS          = 40

    # ack
    ACK             = 250


class AckCode(IntEnum):
    OK              = 0
    BAD_FORMAT      = 1
    CRC_FAIL        = 2
    INVALID_SESSION = 3
    SEQ_OLD_OR_DUP  = 4
    NOT_SUPPORTED   = 5
    RUNTIME_ERROR   = 6


# Keep numeric values aligned with your control modes (C++ WireControlMode)
class WireControlMode(IntEnum):
    Unknown  = 0
    Manual   = 1
    Auto     = 2
    Failsafe = 3


# =============================================================================
# PacketHeader (48 bytes, packed)
# Endianness: CURRENTLY host endian in C++; on Linux this is little-endian.
# =============================================================================

# Layout (must match C++ PacketHeader exactly):
# u32 magic
# u16 version
# u8  msg_type
# u8  reserved0
# u16 flags
# u16 reserved1
# u32 seq
# u64 session_id
# u32 payload_len
# u32 ack_seq
# u32 send_time_ms
# u32 reserved2
# u32 header_crc32c
# u32 payload_crc32c
_HDR_STRUCT = struct.Struct("<I H B B H H I Q I I I I I I")
HEADER_SIZE: int = _HDR_STRUCT.size  # expected 48
assert HEADER_SIZE == 48, f"PacketHeader must be 48 bytes, got {HEADER_SIZE}"
# Backward-compatible aliases (for older imports)
K_HEADER_SIZE: int = HEADER_SIZE
K_MAX_PAYLOAD: int = K_MAX_PAYLOAD_BYTES


@dataclass
class PacketHeader:
    magic: int = K_MAGIC
    version: int = K_PROTO_VERSION

    msg_type: int = 0
    reserved0: int = 0

    flags: int = 0
    reserved1: int = 0

    seq: int = 0
    session_id: int = 0

    payload_len: int = 0
    ack_seq: int = 0

    send_time_ms: int = 0
    reserved2: int = 0

    header_crc32c: int = 0
    payload_crc32c: int = 0

    def pack(self) -> bytes:
        return _HDR_STRUCT.pack(
            self.magic & 0xFFFFFFFF,
            self.version & 0xFFFF,
            self.msg_type & 0xFF,
            self.reserved0 & 0xFF,
            self.flags & 0xFFFF,
            self.reserved1 & 0xFFFF,
            self.seq & 0xFFFFFFFF,
            self.session_id & 0xFFFFFFFFFFFFFFFF,
            self.payload_len & 0xFFFFFFFF,
            self.ack_seq & 0xFFFFFFFF,
            self.send_time_ms & 0xFFFFFFFF,
            self.reserved2 & 0xFFFFFFFF,
            self.header_crc32c & 0xFFFFFFFF,
            self.payload_crc32c & 0xFFFFFFFF,
        )

    @staticmethod
    def unpack(buf: bytes, offset: int = 0) -> "PacketHeader":
        (magic, version, msg_type, reserved0,
         flags, reserved1, seq, session_id,
         payload_len, ack_seq, send_time_ms, reserved2,
         header_crc32c, payload_crc32c) = _HDR_STRUCT.unpack_from(buf, offset)

        return PacketHeader(
            magic=magic,
            version=version,
            msg_type=msg_type,
            reserved0=reserved0,
            flags=flags,
            reserved1=reserved1,
            seq=seq,
            session_id=session_id,
            payload_len=payload_len,
            ack_seq=ack_seq,
            send_time_ms=send_time_ms,
            reserved2=reserved2,
            header_crc32c=header_crc32c,
            payload_crc32c=payload_crc32c,
        )


# =============================================================================
# Basic validation helpers (mirror C++ behavior)
# =============================================================================

def msg_type_known(mt: int) -> bool:
    try:
        MsgType(mt)
        return True
    except ValueError:
        return False


def header_basic_valid(h: PacketHeader) -> Tuple[bool, str]:
    if h.magic != K_MAGIC:
        return False, "bad magic"
    if h.version != K_PROTO_VERSION:
        return False, "bad version"
    if not msg_type_known(h.msg_type):
        return False, "unknown msg_type"
    if h.payload_len > K_MAX_PAYLOAD_BYTES:
        return False, "payload_len too large"
    return True, "ok"
