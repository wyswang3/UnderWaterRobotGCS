from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from .crc32c import crc32c

# Wire-level protocol: MUST match C++ proto_gcs/gcs_protocol.hpp
from urogcs.protocol.wire import (
    PacketHeader,
    HEADER_SIZE,
    K_MAGIC,
    K_PROTO_VERSION,
    K_MAX_PAYLOAD_BYTES,
    K_AUTO_NAME_MAX_LEN,
    K_CTRL_NAME_MAX_LEN,
    Flags,
    MsgType,
    AckCode,
    WireControlMode,
)

# High-level payload models / helpers (safe to keep here)
from urogcs.protocol.messages import DofCommand, StatusTelemetry, clamp_cstr


# =============================================================================
# Time helpers
# =============================================================================

def now_steady_ms() -> int:
    # Align with monotonic "steady" milliseconds; keep uint32 wrap semantics.
    return int(time.monotonic() * 1000.0) & 0xFFFFFFFF


# =============================================================================
# Header helpers
# =============================================================================

def make_header(
    msg_type: MsgType,
    seq: int,
    session_id: int,
    flags: Flags,
    payload_len: int,
) -> PacketHeader:
    return PacketHeader(
        magic=K_MAGIC,
        version=K_PROTO_VERSION,
        msg_type=int(msg_type) & 0xFF,
        reserved0=0,
        flags=int(flags) & 0xFFFF,
        reserved1=0,
        seq=seq & 0xFFFFFFFF,
        session_id=session_id & 0xFFFFFFFFFFFFFFFF,
        payload_len=payload_len & 0xFFFFFFFF,
        ack_seq=0,
        send_time_ms=now_steady_ms(),
        reserved2=0,
        header_crc32c=0,
        payload_crc32c=0,
    )


def header_zero_crc(h: PacketHeader) -> PacketHeader:
    # Create a copy with CRC fields zeroed (matches C++ header_zero_crc)
    return PacketHeader(
        magic=h.magic,
        version=h.version,
        msg_type=h.msg_type,
        reserved0=h.reserved0,
        flags=h.flags,
        reserved1=h.reserved1,
        seq=h.seq,
        session_id=h.session_id,
        payload_len=h.payload_len,
        ack_seq=h.ack_seq,
        send_time_ms=h.send_time_ms,
        reserved2=h.reserved2,
        header_crc32c=0,
        payload_crc32c=0,
    )


def calc_header_crc(h: PacketHeader) -> int:
    # C++: crc32c(&header_zero_crc(h), sizeof(PacketHeader))
    return crc32c(header_zero_crc(h).pack())


def header_basic_valid(h: PacketHeader) -> Tuple[bool, str]:
    if h.magic != K_MAGIC:
        return False, "bad magic"
    if h.version != K_PROTO_VERSION:
        return False, "bad version"
    try:
        MsgType(h.msg_type)
    except ValueError:
        return False, "unknown msg_type"
    if int(h.payload_len) > int(K_MAX_PAYLOAD_BYTES):
        return False, "payload_len too large"
    return True, "ok"


# =============================================================================
# Parse result
# =============================================================================

@dataclass(frozen=True)
class ParsedPacket:
    hdr: PacketHeader
    payload: bytes


# =============================================================================
# Packet build / parse
# =============================================================================

def build_packet(h_in: PacketHeader, payload: bytes) -> bytes:
    # Copy header to avoid mutating caller state
    h = PacketHeader(
        magic=h_in.magic,
        version=h_in.version,
        msg_type=h_in.msg_type,
        reserved0=h_in.reserved0,
        flags=h_in.flags,
        reserved1=h_in.reserved1,
        seq=h_in.seq,
        session_id=h_in.session_id,
        payload_len=h_in.payload_len,
        ack_seq=h_in.ack_seq,
        send_time_ms=h_in.send_time_ms,
        reserved2=h_in.reserved2,
        header_crc32c=0,
        payload_crc32c=0,
    )

    if len(payload) != int(h.payload_len):
        raise ValueError(
            f"payload size mismatch: len(payload)={len(payload)} != hdr.payload_len={int(h.payload_len)}"
        )

    # payload CRC: len==0 => 0 (matches C++)
    h.payload_crc32c = 0 if int(h.payload_len) == 0 else crc32c(payload)

    # header CRC with CRC fields zeroed
    h.header_crc32c = calc_header_crc(h)

    return h.pack() + payload


def parse_and_validate(packet: bytes) -> Tuple[Optional[ParsedPacket], AckCode, str]:
    if len(packet) < HEADER_SIZE:
        return None, AckCode.BAD_FORMAT, "packet too small for header"

    hdr = PacketHeader.unpack(packet[:HEADER_SIZE])

    ok, reason = header_basic_valid(hdr)
    if not ok:
        return None, AckCode.BAD_FORMAT, f"header_basic_valid failed: {reason}"

    total = HEADER_SIZE + int(hdr.payload_len)
    if len(packet) != total:
        return None, AckCode.BAD_FORMAT, "size mismatch: bytes.size != header+payload_len"

    # header CRC
    hc = calc_header_crc(hdr)
    if hc != int(hdr.header_crc32c):
        return None, AckCode.CRC_FAIL, "header CRC32C mismatch"

    payload = packet[HEADER_SIZE:total]

    # payload CRC
    if int(hdr.payload_len) == 0:
        if int(hdr.payload_crc32c) != 0:
            return None, AckCode.CRC_FAIL, "payload_len=0 but payload_crc32c != 0"
    else:
        pc = crc32c(payload)
        if pc != int(hdr.payload_crc32c):
            return None, AckCode.CRC_FAIL, "payload CRC32C mismatch"

    return ParsedPacket(hdr=hdr, payload=payload), AckCode.OK, ""


# =============================================================================
# POD payload layouts (must match C++ static_assert sizes)
# =============================================================================

_CONNECT_REQ     = struct.Struct("<Q")             # 8
_CONNECT_ACK     = struct.Struct("<Q Q I I")       # 24
_CONNECT_CONFIRM = struct.Struct("<Q")             # 8
_HEARTBEAT       = struct.Struct("<I")             # 4
_SET_MODE        = struct.Struct("<B B H 16s")     # 20 (kAutoNameMaxLen=16)
_SET_DOF         = struct.Struct("<6f")            # 24
_ESTOP           = struct.Struct("<B B H")         # 4
_ARM             = struct.Struct("<B B H")         # 4  ★ 新增：ArmCmd 结构，与 EstopCmd 相同

# C++ AckPayload is ONLY 4 bytes: u16 ack_code, u16 reason. ack_seq is in header.ack_seq.
_ACK_PAYLOAD     = struct.Struct("<H H")           # 4

# StatusTelemetry legacy layout:
# <4B 2B H 16s 16s I I Q> = 56 bytes
_STATUS_LEGACY   = struct.Struct("<4B 2B H 16s 16s I I Q")  # 56

# StatusTelemetry v1 layout (pre-nav-diagnostics extension):
# <14B H H H I I I Q 16s 16s Q> = 80 bytes
_STATUS_V1       = struct.Struct("<14B H H H I I I Q 16s 16s Q")  # 80

# StatusTelemetry v2 layout (adds nav_fault_code/nav_status_flags):
# <14B H H H H I I I Q 16s 16s Q> = 82 bytes
_STATUS_V2       = struct.Struct("<14B H H H H I I I Q 16s 16s Q")  # 82


# =============================================================================
# Encode / decode helpers
# =============================================================================

def encode_connect_req(seq: int, gcs_nonce: int, flags: Flags = Flags(0)) -> bytes:
    payload = _CONNECT_REQ.pack(gcs_nonce & 0xFFFFFFFFFFFFFFFF)
    h = make_header(MsgType.CONNECT_REQ, seq, 0, flags, len(payload))
    return build_packet(h, payload)


def decode_connect_ack(payload: bytes) -> Tuple[int, int, int, int]:
    # returns (gcs_nonce_echo, rov_nonce, rov_caps, result_code)
    if len(payload) != _CONNECT_ACK.size:
        raise ValueError(f"CONNECT_ACK payload size mismatch: {len(payload)} != {_CONNECT_ACK.size}")
    return _CONNECT_ACK.unpack(payload)


def encode_connect_confirm(
    seq: int,
    session_id: int,
    rov_nonce_echo: int,
    flags: Flags = Flags(0),
) -> bytes:
    payload = _CONNECT_CONFIRM.pack(rov_nonce_echo & 0xFFFFFFFFFFFFFFFF)
    h = make_header(MsgType.CONNECT_CONFIRM, seq, session_id, flags, len(payload))
    return build_packet(h, payload)


def encode_heartbeat(
    seq: int,
    session_id: int,
    now_ms: int,
    flags: Flags = Flags(0),
    allow_empty: bool = False,
) -> bytes:
    payload = b"" if allow_empty else _HEARTBEAT.pack(now_ms & 0xFFFFFFFF)
    h = make_header(MsgType.HEARTBEAT, seq, session_id, flags, len(payload))
    return build_packet(h, payload)


def encode_set_mode(
    seq: int,
    session_id: int,
    mode: WireControlMode,
    auto_controller: str = "",
    flags: Flags = Flags(0),
) -> bytes:
    name16 = clamp_cstr(auto_controller, K_AUTO_NAME_MAX_LEN)
    payload = _SET_MODE.pack(int(mode) & 0xFF, 0, 0, name16)
    h = make_header(MsgType.SET_MODE, seq, session_id, flags, len(payload))
    return build_packet(h, payload)


def encode_set_dof(seq: int, session_id: int, cmd: DofCommand, flags: Flags = Flags(0)) -> bytes:
    payload = _SET_DOF.pack(*cmd.as_list6())
    h = make_header(MsgType.SET_DOF_CMD, seq, session_id, flags, len(payload))
    return build_packet(h, payload)


def encode_estop(seq: int, session_id: int, enable: bool, flags: Flags = Flags(0)) -> bytes:
    payload = _ESTOP.pack(1 if enable else 0, 0, 0)
    h = make_header(MsgType.ESTOP, seq, session_id, flags, len(payload))
    return build_packet(h, payload)

def encode_arm(seq: int,
               session_id: int,
               armed: bool,
               flags: Flags = Flags(0)) -> bytes:
    """
    ARM / DISARM 命令编码：
      - MsgType = ARM (23)
      - payload: 3 字节
          [0] = 1 if armed else 0
          [1] = 0 (保留)
          [2] = 0 (保留)
    """
    payload = _ARM.pack(1 if armed else 0, 0, 0)

    h = make_header(
        MsgType.ARM,      # ★ 新增的枚举值
        seq,
        session_id,
        flags,
        len(payload),
    )
    return build_packet(h, payload)

def encode_ack(
    seq: int,
    session_id: int,
    ack_seq: int,
    ack_code: AckCode,
    reason: int = 0,
) -> bytes:
    """
    C++ contract:
      - header.flags includes Flags.IS_ACK
      - header.ack_seq carries the sequence being acknowledged
      - payload is AckPayload {u16 ack_code, u16 reason}
    """
    payload = _ACK_PAYLOAD.pack(int(ack_code) & 0xFFFF, reason & 0xFFFF)
    h = make_header(MsgType.ACK, seq, session_id, Flags.IS_ACK, len(payload))
    h.ack_seq = ack_seq & 0xFFFFFFFF
    return build_packet(h, payload)


def decode_ack(hdr: PacketHeader, payload: bytes) -> Tuple[int, int, int]:
    """
    returns (ack_seq, ack_code_u16, reason)
    ack_seq is taken from header.ack_seq
    """
    if len(payload) != _ACK_PAYLOAD.size:
        raise ValueError(f"ACK payload size mismatch: {len(payload)} != {_ACK_PAYLOAD.size}")
    ack_code_u16, reason = _ACK_PAYLOAD.unpack(payload)
    return int(hdr.ack_seq), int(ack_code_u16), int(reason)


def decode_status(payload: bytes) -> StatusTelemetry:
    if len(payload) == _STATUS_V2.size:
        (session_established, link_alive, estop, armed,
         mode, failsafe_active, nav_valid, nav_state,
         nav_stale, nav_degraded, fault_state, health_state,
         command_status, _reserved0,
         last_fault_code,
         command_fault_code, nav_fault_code, nav_status_flags,
         consecutive_failures, auto_fail_limit, status_seq,
         command_cmd_seq,
         active16, desired16,
         t_ns) = _STATUS_V2.unpack(payload)

        def cstr(bs: bytes) -> str:
            return bs.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")

        return StatusTelemetry(
            session_established=int(session_established),
            link_alive=int(link_alive),
            estop=int(estop),
            armed=int(armed),
            mode=int(mode),
            failsafe_active=int(failsafe_active),
            nav_valid=int(nav_valid),
            nav_state=int(nav_state),
            nav_stale=int(nav_stale),
            nav_degraded=int(nav_degraded),
            fault_state=int(fault_state),
            health_state=int(health_state),
            command_status=int(command_status),
            last_fault_code=int(last_fault_code),
            command_fault_code=int(command_fault_code),
            nav_fault_code=int(nav_fault_code),
            nav_status_flags=int(nav_status_flags),
            active_controller=cstr(active16),
            desired_controller=cstr(desired16),
            consecutive_failures=int(consecutive_failures),
            auto_fail_limit=int(auto_fail_limit),
            status_seq=int(status_seq),
            command_cmd_seq=int(command_cmd_seq),
            t_ns=int(t_ns),
        )

    if len(payload) == _STATUS_V1.size:
        (session_established, link_alive, estop, armed,
         mode, failsafe_active, nav_valid, nav_state,
         nav_stale, nav_degraded, fault_state, health_state,
         command_status, _reserved0,
         last_fault_code,
         command_fault_code, _reserved1,
         consecutive_failures, auto_fail_limit, status_seq,
         command_cmd_seq,
         active16, desired16,
         t_ns) = _STATUS_V1.unpack(payload)

        def cstr(bs: bytes) -> str:
            return bs.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")

        return StatusTelemetry(
            session_established=int(session_established),
            link_alive=int(link_alive),
            estop=int(estop),
            armed=int(armed),
            mode=int(mode),
            failsafe_active=int(failsafe_active),
            nav_valid=int(nav_valid),
            nav_state=int(nav_state),
            nav_stale=int(nav_stale),
            nav_degraded=int(nav_degraded),
            fault_state=int(fault_state),
            health_state=int(health_state),
            command_status=int(command_status),
            last_fault_code=int(last_fault_code),
            command_fault_code=int(command_fault_code),
            active_controller=cstr(active16),
            desired_controller=cstr(desired16),
            consecutive_failures=int(consecutive_failures),
            auto_fail_limit=int(auto_fail_limit),
            status_seq=int(status_seq),
            command_cmd_seq=int(command_cmd_seq),
            t_ns=int(t_ns),
        )

    if len(payload) != _STATUS_LEGACY.size:
        raise ValueError(
            "STATUS payload size mismatch: "
            f"{len(payload)} not in ({_STATUS_LEGACY.size}, {_STATUS_V1.size}, {_STATUS_V2.size})"
        )
    (session_established, link_alive, estop, _r0,
     mode, _r1, _r2,
     active16, desired16,
     consecutive_failures, auto_fail_limit,
     t_ns) = _STATUS_LEGACY.unpack(payload)

    def cstr(bs: bytes) -> str:
        return bs.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")

    return StatusTelemetry(
        session_established=int(session_established),
        link_alive=int(link_alive),
        estop=int(estop),
        mode=int(mode),
        active_controller=cstr(active16),
        desired_controller=cstr(desired16),
        consecutive_failures=int(consecutive_failures),
        auto_fail_limit=int(auto_fail_limit),
        t_ns=int(t_ns),
    )
