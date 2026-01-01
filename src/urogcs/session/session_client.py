from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from urogcs.protocol.codec import (
    parse_and_validate,
    decode_connect_ack,
    decode_status,
    decode_ack,  # NEW: decode_ack(hdr, payload) -> (ack_seq, ack_code_u16, reason)
    encode_connect_req,
    encode_connect_confirm,
    encode_heartbeat,
    encode_set_mode,
    encode_set_dof,
    encode_estop,
)
from urogcs.protocol.wire import (
    MsgType,
    AckCode,
    Flags,
    WireControlMode,
)

from urogcs.protocol.messages import DofCommand, StatusTelemetry


# =============================================================================
# Debug logger (default OFF)
# =============================================================================

@dataclass
class DebugConfig:
    enabled: bool = False
    rx_hex: bool = False          # 打印收到的包十六进制（建议先关，必要时开）
    tx_hex: bool = False          # 打印发送包十六进制
    max_hex_bytes: int = 96       # hex 打印截断长度
    verbose_poll: bool = False    # poll 每包打印


def _hexdump(b: bytes, max_len: int = 96) -> str:
    if not b:
        return ""
    bb = b[:max_len]
    s = " ".join(f"{x:02x}" for x in bb)
    if len(b) > max_len:
        s += f" ...(+{len(b)-max_len})"
    return s


# =============================================================================
# State
# =============================================================================

@dataclass
class SessionState:
    established: bool = False
    session_id: int = 0

    gcs_nonce: int = 0
    rov_nonce: int = 0

    # sequencing
    tx_seq: int = 1      # wire header.seq for client->server packets
    cmd_seq: int = 1     # if you need separate command sequence later


@dataclass
class HandshakeConfig:
    timeout_s: float = 2.0
    confirm_ack_timeout_s: float = 2.0
    rx_poll_max_packets: int = 32
    require_confirm_ack: bool = True
    allow_status_established: bool = True
    debug: bool = False


# =============================================================================
# Client
# =============================================================================

class GcsSessionClient:
    def __init__(
        self,
        rov_addr: Tuple[str, int],
        bind_addr: Tuple[str, int] = ("0.0.0.0", 14551),
        recv_timeout_ms: int = 20,
        on_status: Optional[Callable[[StatusTelemetry], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        debug: Optional[bool] = None,  # if None -> env UROGCS_DEBUG
    ) -> None:
        self.rov_addr = rov_addr
        self.bind_addr = bind_addr
        self.recv_timeout_ms = int(recv_timeout_ms)

        self.on_status = on_status
        self.on_log = on_log

        env_dbg = os.getenv("UROGCS_DEBUG", "0").strip() not in ("0", "", "false", "False")
        dbg_enabled = env_dbg if debug is None else bool(debug)
        self.dbg = DebugConfig(enabled=dbg_enabled)

        # allow finer toggles
        self.dbg.rx_hex = os.getenv("UROGCS_DEBUG_RX_HEX", "0") == "1"
        self.dbg.tx_hex = os.getenv("UROGCS_DEBUG_TX_HEX", "0") == "1"
        self.dbg.verbose_poll = os.getenv("UROGCS_DEBUG_VERBOSE_POLL", "0") == "1"
        try:
            self.dbg.max_hex_bytes = int(os.getenv("UROGCS_DEBUG_MAX_HEX", str(self.dbg.max_hex_bytes)))
        except Exception:
            pass

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(self.bind_addr)
        self.sock.settimeout(max(0.001, self.recv_timeout_ms / 1000.0))

        self.st = SessionState()

        self.last_error: str = ""
        self._last_status: Optional[StatusTelemetry] = None

        # handshake ack tracking
        self._pending_ack_seq: Optional[int] = None
        self._pending_ack_code: Optional[AckCode] = None
        self._pending_ack_reason: Optional[int] = None

        self._log(f"[INIT] bind={self.bind_addr[0]}:{self.bind_addr[1]} target={self.rov_addr[0]}:{self.rov_addr[1]}")
        if self.dbg.enabled:
            self._log(f"[DBG] enabled=1 rx_hex={int(self.dbg.rx_hex)} tx_hex={int(self.dbg.tx_hex)} verbose_poll={int(self.dbg.verbose_poll)}")

    # -------------------------------------------------------------------------
    # logging helpers
    # -------------------------------------------------------------------------

    def _log(self, s: str) -> None:
        if self.on_log:
            try:
                self.on_log(s)
            except Exception:
                pass
        # 调试时同时打印到 stdout，方便你在 TUI 里看到
        if self.dbg.enabled:
            print(s, flush=True)

    def _set_err(self, s: str) -> None:
        self.last_error = s
        self._log(s)

    # -------------------------------------------------------------------------
    # transport
    # -------------------------------------------------------------------------

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def _send(self, pkt: bytes) -> None:
        if self.dbg.enabled:
            self._log(f"[TX] -> {self.rov_addr} bytes={len(pkt)}")
            if self.dbg.tx_hex:
                self._log(f"[TX_HEX] { _hexdump(pkt, self.dbg.max_hex_bytes) }")
        self.sock.sendto(pkt, self.rov_addr)

    def _recv_once(self) -> Optional[Tuple[bytes, Tuple[str, int]]]:
        try:
            data, addr = self.sock.recvfrom(2048)
            if self.dbg.enabled:
                self._log(f"[RX] <- {addr} bytes={len(data)}")
                if self.dbg.rx_hex:
                    self._log(f"[RX_HEX] { _hexdump(data, self.dbg.max_hex_bytes) }")
            return data, addr
        except socket.timeout:
            return None
        except Exception as e:
            self._log(f"[RX] recv error: {e}")
            return None

    # -------------------------------------------------------------------------
    # packet handlers
    # -------------------------------------------------------------------------

    def _handle_connect_ack(self, session_id: int, payload: bytes, debug: bool = False) -> bool:
        try:
            gcs_nonce_echo, rov_nonce, rov_caps, result_code = decode_connect_ack(payload)
        except Exception as e:
            self._log(f"[HS] CONNECT_ACK decode error: {e}")
            return False

        if result_code != 0:
            self._log(f"[HS] CONNECT_ACK result_code={result_code} (reject)")
            return False

        if gcs_nonce_echo != self.st.gcs_nonce:
            self._log(f"[HS] CONNECT_ACK nonce mismatch: echo={gcs_nonce_echo} expected={self.st.gcs_nonce}")
            return False

        if session_id == 0 or rov_nonce == 0:
            self._log(f"[HS] CONNECT_ACK invalid: session_id={session_id} rov_nonce={rov_nonce}")
            return False

        self.st.session_id = int(session_id)
        self.st.rov_nonce = int(rov_nonce)

        self._log(f"[HS] got CONNECT_ACK session_id={self.st.session_id} rov_nonce={self.st.rov_nonce} caps={rov_caps}")
        return True

    def _handle_ack(self, hdr, payload: bytes) -> None:
        """
        NEW ACK contract:
          - hdr.ack_seq is the seq being acknowledged
          - payload is 4 bytes: u16 ack_code, u16 reason
        """
        try:
            ack_seq, ack_code_u16, reason = decode_ack(hdr, payload)
            code = AckCode(int(ack_code_u16))
        except Exception as e:
            self._log(f"[RX][ACK] decode failed: {e}")
            return

        if self.dbg.enabled:
            self._log(f"[RX][ACK] ack_seq={ack_seq} code={code.name} reason={reason}")

        if self._pending_ack_seq is not None and int(ack_seq) == int(self._pending_ack_seq):
            self._pending_ack_code = code
            self._pending_ack_reason = int(reason)
            self._log(f"[RX][ACK] matched pending ack_seq={ack_seq} code={code.name}")

    def _status_indicates_established(self) -> bool:
        st = self._last_status
        if not st:
            return False
        # C++ StatusTelemetry.session_established: 0/1
        return int(st.session_established) == 1

    # -------------------------------------------------------------------------
    # poll
    # -------------------------------------------------------------------------

    def poll(self, max_packets: int = 16) -> None:
        """
        Pull up to max_packets from UDP, parse, and dispatch.
        """
        for _ in range(max_packets):
            rx = self._recv_once()
            if not rx:
                return
            data, addr = rx

            pp, code, err = parse_and_validate(data)
            if not pp:
                # 这条日志是你目前最需要的：说明为啥 ACK/STATUS 被丢弃
                self._log(f"[RX] parse failed: {code.name} {err} from {addr} len={len(data)}")
                continue

            mt = MsgType(pp.hdr.msg_type)

            if self.dbg.enabled and self.dbg.verbose_poll:
                self._log(f"[RX] parsed mt={mt.name} seq={pp.hdr.seq} sid={pp.hdr.session_id} flags=0x{pp.hdr.flags:04x} plen={pp.hdr.payload_len} ack_seq={pp.hdr.ack_seq}")

            if mt == MsgType.STATUS:
                try:
                    st = decode_status(pp.payload)
                    self._last_status = st
                    if self.on_status:
                        self.on_status(st)
                except Exception as e:
                    self._log(f"[RX][STATUS] decode error: {e}")
                continue

            if mt == MsgType.ACK:
                self._handle_ack(pp.hdr, pp.payload)
                continue

            # other packets can be added later
            # self._log(f"[RX] ignore mt={mt.name}")

    # -------------------------------------------------------------------------
    # handshake
    # -------------------------------------------------------------------------

    def handshake(self, timeout_s: float = 2.0, hs_cfg: Optional[HandshakeConfig] = None) -> bool:
        """
        Robust handshake:
        - CONNECT_REQ -> wait CONNECT_ACK
        - CONNECT_CONFIRM (ACK_REQ)
        - wait ACK(match confirm_seq) OR (optional) STATUS indicates established
        """
        cfg = hs_cfg or HandshakeConfig(timeout_s=timeout_s)
        if self.dbg.enabled:
            cfg.debug = True  # 调试模式自动打开更详细行为

        # reset state
        self.last_error = ""
        self.st.established = False
        self.st.session_id = 0
        self.st.rov_nonce = 0
        self.st.cmd_seq = 1
        self.st.tx_seq = 1
        self._pending_ack_seq = None
        self._pending_ack_code = None
        self._pending_ack_reason = None
        self._last_status = None

        # client nonce
        self.st.gcs_nonce = int.from_bytes(os.urandom(8), "little")

        # 1) send CONNECT_REQ
        req_seq = self.st.tx_seq
        pkt = encode_connect_req(seq=req_seq, gcs_nonce=self.st.gcs_nonce, flags=Flags(0))
        self._send(pkt)
        self._log(f"[HS] sent CONNECT_REQ seq={req_seq} gcs_nonce={self.st.gcs_nonce}")
        self.st.tx_seq += 1

        # 2) wait CONNECT_ACK
        t0 = time.time()
        got_connect_ack = False

        while time.time() - t0 < cfg.timeout_s:
            rx = self._recv_once()
            if not rx:
                continue
            data, addr = rx

            pp, code, err = parse_and_validate(data)
            if not pp:
                self._log(f"[HS] parse failed: {code.name} {err} from {addr} len={len(data)}")
                continue

            mt = MsgType(pp.hdr.msg_type)

            if cfg.debug:
                self._log(f"[HS][DBG] mt={mt.name} seq={pp.hdr.seq} sid={pp.hdr.session_id} flags=0x{pp.hdr.flags:04x} plen={pp.hdr.payload_len} ack_seq={pp.hdr.ack_seq}")

            if mt == MsgType.CONNECT_ACK:
                got_connect_ack = self._handle_connect_ack(pp.hdr.session_id, pp.payload, debug=cfg.debug)
                if got_connect_ack:
                    break
                continue

            # allow STATUS/ACK background
            if mt == MsgType.STATUS:
                try:
                    st = decode_status(pp.payload)
                    self._last_status = st
                    if self.on_status:
                        self.on_status(st)
                except Exception as e:
                    self._log(f"[HS] STATUS decode error: {e}")
                continue

            if mt == MsgType.ACK:
                # 通常不会在这一阶段收到 ACK，但也不应崩
                self._handle_ack(pp.hdr, pp.payload)
                continue

        if not got_connect_ack:
            self._set_err("[HS] CONNECT_ACK timeout")
            return False

        if self.st.session_id == 0 or self.st.rov_nonce == 0:
            self._set_err(f"[HS] invalid session params: session_id={self.st.session_id} rov_nonce={self.st.rov_nonce}")
            return False

        # 3) send CONNECT_CONFIRM with ACK_REQ
        confirm_seq = self.st.tx_seq
        pkt2 = encode_connect_confirm(
            seq=confirm_seq,
            session_id=self.st.session_id,
            rov_nonce_echo=self.st.rov_nonce,
            flags=Flags.ACK_REQ,
        )
        self._pending_ack_seq = int(confirm_seq)
        self._pending_ack_code = None
        self._pending_ack_reason = None

        self._send(pkt2)
        self._log(f"[HS] sent CONNECT_CONFIRM seq={confirm_seq} session_id={self.st.session_id}")
        self.st.tx_seq += 1

        # 4) wait confirm ACK or STATUS established
        t1 = time.time()
        while time.time() - t1 < cfg.confirm_ack_timeout_s:
            self.poll(max_packets=cfg.rx_poll_max_packets)

            if cfg.allow_status_established and self._status_indicates_established():
                self.st.established = True
                self._log("[HS] established via STATUS")
                return True

            if cfg.require_confirm_ack and self._pending_ack_code is not None:
                if self._pending_ack_code == AckCode.OK:
                    self.st.established = True
                    self._log("[HS] established via CONFIRM ACK")
                    return True
                self._set_err(f"[HS] CONNECT_CONFIRM rejected: {self._pending_ack_code.name} reason={self._pending_ack_reason}")
                return False

            time.sleep(0.005)

        if cfg.require_confirm_ack:
            self._set_err("[HS] CONNECT_CONFIRM ACK timeout")
            return False

        self.st.established = True
        self._log("[HS] established (optimistic)")
        return True

    # -------------------------------------------------------------------------
    # command send APIs
    # -------------------------------------------------------------------------

    def send_heartbeat(self, use_session: bool = True, ack_req: bool = False) -> None:
        sid = self.st.session_id if use_session else 0
        flags = Flags.ACK_REQ if ack_req else Flags(0)
        pkt = encode_heartbeat(seq=self.st.tx_seq, session_id=sid, now_ms=int(time.monotonic() * 1000) & 0xFFFFFFFF, flags=flags)
        self._send(pkt)
        self.st.tx_seq += 1

    def send_set_mode(self, mode: WireControlMode, auto_controller: str = "", ack_req: bool = True) -> None:
        flags = Flags.ACK_REQ if ack_req else Flags(0)
        pkt = encode_set_mode(seq=self.st.tx_seq, session_id=self.st.session_id, mode=mode, auto_controller=auto_controller, flags=flags)
        if ack_req:
            self._pending_ack_seq = self.st.tx_seq
            self._pending_ack_code = None
            self._pending_ack_reason = None
        self._send(pkt)
        self.st.tx_seq += 1

    def send_set_dof(self, cmd: DofCommand, ack_req: bool = False) -> None:
        flags = Flags.ACK_REQ if ack_req else Flags(0)
        pkt = encode_set_dof(seq=self.st.tx_seq, session_id=self.st.session_id, cmd=cmd, flags=flags)
        if ack_req:
            self._pending_ack_seq = self.st.tx_seq
            self._pending_ack_code = None
            self._pending_ack_reason = None
        self._send(pkt)
        self.st.tx_seq += 1

    def send_estop(self, enable: bool, ack_req: bool = True) -> None:
        flags = Flags.ACK_REQ if ack_req else Flags(0)
        pkt = encode_estop(seq=self.st.tx_seq, session_id=self.st.session_id, enable=enable, flags=flags)
        if ack_req:
            self._pending_ack_seq = self.st.tx_seq
            self._pending_ack_code = None
            self._pending_ack_reason = None
        self._send(pkt)
        self.st.tx_seq += 1
