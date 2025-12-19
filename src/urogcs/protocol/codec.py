# src/urogcs/protocol/codec.py
from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from .crc32c import crc32c
from .messages import (
    MsgType, AckCode, WireControlMode,
    FLAG_ACK_REQ, FLAG_IS_ACK,
    K_MAGIC, K_PROTO_VERSION, K_MAX_PAYLOAD, K_HEADER_SIZE,
    K_AUTO_NAME_MAX_LEN, K_CTRL_NAME_MAX_LEN,
    DofCommand, StatusTelemetry, clamp_cstr
)

# PacketHeader: packed 40 bytes (see your proto_gcs/gcs_protocol.hpp)
# Use little-endian to match Windows/ARM64 typical "host endian".
_HDR = struct.Struct("<I H B B H H I Q I I I I")
assert _HDR.size == K_HEADER_SIZE

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
    send_time_ms: int = 0
    header_crc32c: int = 0
    payload_crc32c: int = 0

    def pack(self) -> bytes:
        return _HDR.pack(
            self.magic & 0xFFFFFFFF,
            self.version & 0xFFFF,
            self.msg_type & 0xFF,
            self.reserved0 & 0xFF,
            self.flags & 0xFFFF,
            self.reserved1 & 0xFFFF,
            self.seq & 0xFFFFFFFF,
            self.session_id & 0xFFFFFFFFFFFFFFFF,
            self.payload_len & 0xFFFFFFFF,
            self.send_time_ms & 0xFFFFFFFF,
            self.header_crc32c & 0xFFFFFFFF,
            self.payload_crc32c & 0xFFFFFFFF,
        )

    @staticmethod
    def unpack(b: bytes) -> "PacketHeader":
        return PacketHeader(*_HDR.unpack(b))


def now_steady_ms() -> int:
    # Align with steady_clock ms "intent"
    return int(time.monotonic() * 1000.0) & 0xFFFFFFFF


def make_header(msg_type: int, seq: int, session_id: int, flags: int, payload_len: int) -> PacketHeader:
    h = PacketHeader()
    h.magic = K_MAGIC
    h.version = K_PROTO_VERSION
    h.msg_type = msg_type & 0xFF
    h.flags = flags & 0xFFFF
    h.seq = seq & 0xFFFFFFFF
    h.session_id = session_id & 0xFFFFFFFFFFFFFFFF
    h.payload_len = payload_len & 0xFFFFFFFF
    h.send_time_ms = now_steady_ms()
    h.header_crc32c = 0
    h.payload_crc32c = 0
    return h


def header_zero_crc(h: PacketHeader) -> PacketHeader:
    hz = PacketHeader(**h.__dict__)
    hz.header_crc32c = 0
    hz.payload_crc32c = 0
    return hz


def calc_header_crc(h: PacketHeader) -> int:
    # C++: crc32c(&header_zero_crc(h), sizeof(PacketHeader))
    return crc32c(header_zero_crc(h).pack())


def header_basic_valid(h: PacketHeader) -> bool:
    if h.magic != K_MAGIC:
        return False
    if h.version != K_PROTO_VERSION:
        return False
    try:
        MsgType(h.msg_type)
    except ValueError:
        return False
    if h.payload_len > K_MAX_PAYLOAD:
        return False
    return True


@dataclass
class ParsedPacket:
    hdr: PacketHeader
    payload: bytes


def build_packet(h_in: PacketHeader, payload: bytes) -> bytes:
    h = PacketHeader(**h_in.__dict__)
    if len(payload) != int(h.payload_len):
        raise ValueError("payload size mismatch vs header.payload_len")

    # payload CRC: special-case len==0 => 0 (matches C++)
    if h.payload_len == 0:
        h.payload_crc32c = 0
    else:
        h.payload_crc32c = crc32c(payload)

    # header CRC with CRC fields zeroed
    h.header_crc32c = calc_header_crc(h)

    return h.pack() + payload


def parse_and_validate(packet: bytes) -> Tuple[Optional[ParsedPacket], AckCode, str]:
    if len(packet) < K_HEADER_SIZE:
        return None, AckCode.BAD_FORMAT, "packet too small for header"

    hdr = PacketHeader.unpack(packet[:K_HEADER_SIZE])

    if not header_basic_valid(hdr):
        return None, AckCode.BAD_FORMAT, "header_basic_valid failed"

    total = K_HEADER_SIZE + int(hdr.payload_len)
    if len(packet) != total:
        return None, AckCode.BAD_FORMAT, "size mismatch: bytes.size != header+payload_len"

    hc = calc_header_crc(hdr)
    if hc != hdr.header_crc32c:
        return None, AckCode.CRC_FAIL, "header CRC32C mismatch"

    payload = packet[K_HEADER_SIZE:total]

    if hdr.payload_len == 0:
        if hdr.payload_crc32c != 0:
            return None, AckCode.CRC_FAIL, "payload_len=0 but payload_crc32c != 0"
    else:
        pc = crc32c(payload)
        if pc != hdr.payload_crc32c:
            return None, AckCode.CRC_FAIL, "payload CRC32C mismatch"

    return ParsedPacket(hdr=hdr, payload=payload), AckCode.OK, ""


# ---- POD payload layouts (exact sizes per static_asserts) ----
_CONNECT_REQ = struct.Struct("<Q")          # 8
_CONNECT_ACK = struct.Struct("<Q Q I I")    # 24
_CONNECT_CONFIRM = struct.Struct("<Q")      # 8
_HEARTBEAT = struct.Struct("<I")            # 4
_SET_MODE = struct.Struct("<B B H 16s")     # 20
_SET_DOF = struct.Struct("<6f")             # 24
_ESTOP = struct.Struct("<B B H")            # 4
_ACK = struct.Struct("<I H H")              # 8
_STATUS = struct.Struct("<4B 2B H 16s 16s I I Q")  # matches StatusTelemetry


# ---- encode helpers ----
def encode_connect_req(seq: int, gcs_nonce: int, flags: int = 0) -> bytes:
    payload = _CONNECT_REQ.pack(gcs_nonce & 0xFFFFFFFFFFFFFFFF)
    h = make_header(int(MsgType.CONNECT_REQ), seq, 0, flags, len(payload))
    return build_packet(h, payload)

def decode_connect_ack(payload: bytes) -> Tuple[int, int, int, int]:
    # returns (gcs_nonce_echo, rov_nonce, rov_caps, result_code)
    return _CONNECT_ACK.unpack(payload)

def encode_connect_confirm(seq: int, session_id: int, rov_nonce_echo: int, flags: int = 0) -> bytes:
    payload = _CONNECT_CONFIRM.pack(rov_nonce_echo & 0xFFFFFFFFFFFFFFFF)
    h = make_header(int(MsgType.CONNECT_CONFIRM), seq, session_id, flags, len(payload))
    return build_packet(h, payload)

def encode_heartbeat(seq: int, session_id: int, now_ms: int, flags: int = 0, allow_empty: bool = False) -> bytes:
    if allow_empty:
        payload = b""
    else:
        payload = _HEARTBEAT.pack(now_ms & 0xFFFFFFFF)
    h = make_header(int(MsgType.HEARTBEAT), seq, session_id, flags, len(payload))
    return build_packet(h, payload)

def encode_set_mode(seq: int, session_id: int, mode: WireControlMode, auto_controller: str = "", flags: int = 0) -> bytes:
    name16 = clamp_cstr(auto_controller, K_AUTO_NAME_MAX_LEN)
    payload = _SET_MODE.pack(int(mode) & 0xFF, 0, 0, name16)
    h = make_header(int(MsgType.SET_MODE), seq, session_id, flags, len(payload))
    return build_packet(h, payload)

def encode_set_dof(seq: int, session_id: int, cmd: DofCommand, flags: int = 0) -> bytes:
    payload = _SET_DOF.pack(*cmd.as_list6())
    h = make_header(int(MsgType.SET_DOF_CMD), seq, session_id, flags, len(payload))
    return build_packet(h, payload)

def encode_estop(seq: int, session_id: int, enable: bool, flags: int = 0) -> bytes:
    payload = _ESTOP.pack(1 if enable else 0, 0, 0)
    h = make_header(int(MsgType.ESTOP), seq, session_id, flags, len(payload))
    return build_packet(h, payload)

def decode_ack(payload: bytes) -> Tuple[int, int, int]:
    # returns (ack_seq, ack_code_u16, reason)
    return _ACK.unpack(payload)

def decode_status(payload: bytes) -> StatusTelemetry:
    (session_established, link_alive, estop, _r0,
     mode, _r1, _r2,
     active16, desired16,
     consecutive_failures, auto_fail_limit,
     t_ns) = _STATUS.unpack(payload)

    def cstr(bs: bytes) -> str:
        return bs.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")

    return StatusTelemetry(
        session_established=session_established,
        link_alive=link_alive,
        estop=estop,
        mode=mode,
        active_controller=cstr(active16),
        desired_controller=cstr(desired16),
        consecutive_failures=consecutive_failures,
        auto_fail_limit=auto_fail_limit,
        t_ns=t_ns,
    )
