# src/urogcs/session/session_client.py
from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from urogcs.protocol.messages import (
    MsgType, AckCode, WireControlMode,
    FLAG_ACK_REQ,
    DofCommand, StatusTelemetry
)
from urogcs.protocol.codec import (
    parse_and_validate,
    encode_connect_req, decode_connect_ack, encode_connect_confirm,
    encode_heartbeat, encode_set_mode, encode_set_dof, encode_estop,
    decode_ack, decode_status
)

StatusCallback = Callable[[StatusTelemetry], None]
LogCallback = Callable[[str], None]

@dataclass
class SessionState:
    established: bool = False
    session_id: int = 0
    gcs_nonce: int = 0
    rov_nonce: int = 0

    # Command seq must be strictly increasing (server rejects <= last_cmd_seq)
    cmd_seq: int = 1

    # General TX seq for non-command packets (handshake/heartbeat); can share same counter if you prefer
    tx_seq: int = 1


class GcsSessionClient:
    """
    Python-side GCS client that matches server-side session rules in comm_gcs::session::GcsSession.

    - handshake: CONNECT_REQ -> CONNECT_ACK -> CONNECT_CONFIRM
    - after established: commands must use correct session_id and monotonic seq
    - strict_session_check: heartbeat may use session_id=0 (optional), commands must not.
    """
    def __init__(self,
                 rov_addr: Tuple[str, int],
                 bind_addr: Tuple[str, int] = ("0.0.0.0", 0),
                 recv_timeout_ms: int = 50,
                 on_status: Optional[StatusCallback] = None,
                 on_log: Optional[LogCallback] = None):
        self.rov_addr = rov_addr
        self.on_status = on_status
        self.on_log = on_log

        self.st = SessionState()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(bind_addr)
        self.sock.settimeout(recv_timeout_ms / 1000.0)

    def _log(self, msg: str) -> None:
        if self.on_log:
            self.on_log(msg)

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def _send(self, pkt: bytes) -> None:
        self.sock.sendto(pkt, self.rov_addr)

    def _recv_once(self) -> Optional[bytes]:
        try:
            data, _ = self.sock.recvfrom(4096)
            return data
        except socket.timeout:
            return None

    def poll(self, max_packets: int = 16) -> None:
        """
        Non-blocking-ish poll. Call frequently in your main loop.
        Handles STATUS / ACK (and can also handle CONNECT_ACK during handshake).
        """
        for _ in range(max_packets):
            data = self._recv_once()
            if not data:
                return
            pp, code, err = parse_and_validate(data)
            if not pp:
                self._log(f"[RX] parse failed: {code.name} {err}")
                continue

            mt = MsgType(pp.hdr.msg_type)
            if mt == MsgType.STATUS:
                try:
                    st = decode_status(pp.payload)
                    if self.on_status:
                        self.on_status(st)
                except Exception as e:
                    self._log(f"[RX] STATUS decode error: {e}")
            elif mt == MsgType.ACK:
                try:
                    ack_seq, ack_code_u16, _reason = decode_ack(pp.payload)
                    ac = AckCode(int(ack_code_u16))
                    self._log(f"[RX] ACK: ack_seq={ack_seq} code={ac.name} (pkt_seq={pp.hdr.seq})")
                except Exception as e:
                    self._log(f"[RX] ACK decode error: {e}")
            elif mt == MsgType.CONNECT_ACK:
                # optional: allow poll() to consume connect ack too
                self._handle_connect_ack(pp.hdr.session_id, pp.payload)
            else:
                self._log(f"[RX] ignored msg_type={mt.name}")

    def _handle_connect_ack(self, session_id: int, payload: bytes) -> bool:
        try:
            gcs_nonce_echo, rov_nonce, _caps, result_code = decode_connect_ack(payload)
        except Exception as e:
            self._log(f"[HS] CONNECT_ACK decode error: {e}")
            return False

        if gcs_nonce_echo != self.st.gcs_nonce:
            self._log(f"[HS] CONNECT_ACK gcs_nonce_echo mismatch: got={gcs_nonce_echo} want={self.st.gcs_nonce}")
            return False
        if result_code != 0:
            self._log(f"[HS] CONNECT_ACK result_code != 0: {result_code}")
            return False

        self.st.session_id = int(session_id) & 0xFFFFFFFFFFFFFFFF
        self.st.rov_nonce = int(rov_nonce) & 0xFFFFFFFFFFFFFFFF
        self._log(f"[HS] CONNECT_ACK ok: session_id={self.st.session_id} rov_nonce={self.st.rov_nonce}")
        return True

    def handshake(self, timeout_s: float = 2.0) -> bool:
        """
        Executes handshake exactly as server expects.

        Server behavior recap:
        - on CONNECT_REQ: sets st_.session_id=random, st_.rov_nonce=random, established=false; sends CONNECT_ACK with header.session_id = st_.session_id and payload.rov_nonce
        - on CONNECT_CONFIRM: requires header.session_id == st_.session_id and payload.rov_nonce_echo == st_.rov_nonce; then established=true
        """
        self.st.established = False
        self.st.session_id = 0
        self.st.cmd_seq = 1
        self.st.tx_seq = 1

        # client nonce
        self.st.gcs_nonce = int.from_bytes(os.urandom(8), "little")

        # 1) send CONNECT_REQ (no session_id)
        pkt = encode_connect_req(seq=self.st.tx_seq, gcs_nonce=self.st.gcs_nonce, flags=0)
        self._send(pkt)
        self._log(f"[HS] sent CONNECT_REQ seq={self.st.tx_seq} gcs_nonce={self.st.gcs_nonce}")
        self.st.tx_seq += 1

        # 2) wait CONNECT_ACK
        t0 = time.time()
        got_ack = False
        while time.time() - t0 < timeout_s:
            data = self._recv_once()
            if not data:
                continue
            pp, code, err = parse_and_validate(data)
            if not pp:
                self._log(f"[HS] parse failed: {code.name} {err}")
                continue
            mt = MsgType(pp.hdr.msg_type)
            if mt != MsgType.CONNECT_ACK:
                # still allow STATUS/ACK in background
                if mt == MsgType.STATUS:
                    try:
                        st = decode_status(pp.payload)
                        if self.on_status:
                            self.on_status(st)
                    except Exception:
                        pass
                continue

            got_ack = self._handle_connect_ack(pp.hdr.session_id, pp.payload)
            if got_ack:
                break

        if not got_ack:
            self._log("[HS] CONNECT_ACK timeout")
            return False

        # 3) send CONNECT_CONFIRM with header.session_id=server session_id
        pkt2 = encode_connect_confirm(
            seq=self.st.tx_seq,
            session_id=self.st.session_id,
            rov_nonce_echo=self.st.rov_nonce,
            flags=FLAG_ACK_REQ,  # optional: ask server to ACK confirm
        )
        self._send(pkt2)
        self._log(f"[HS] sent CONNECT_CONFIRM seq={self.st.tx_seq} session_id={self.st.session_id}")
        self.st.tx_seq += 1

        # Server sets established=true immediately; we treat handshake success as "confirm sent"
        self.st.established = True
        return True

    # ----- Commands (require established + correct session_id + monotonic cmd_seq) -----

    def send_estop(self, enable: bool, ack_req: bool = True) -> None:
        if not self.st.established or self.st.session_id == 0:
            raise RuntimeError("session not established")
        flags = FLAG_ACK_REQ if ack_req else 0
        pkt = encode_estop(self.st.cmd_seq, self.st.session_id, enable=enable, flags=flags)
        self._send(pkt)
        self._log(f"[TX] ESTOP enable={int(enable)} seq={self.st.cmd_seq}")
        self.st.cmd_seq += 1

    def send_set_mode(self, mode: WireControlMode, auto_controller: str = "", ack_req: bool = True) -> None:
        if not self.st.established or self.st.session_id == 0:
            raise RuntimeError("session not established")
        flags = FLAG_ACK_REQ if ack_req else 0
        pkt = encode_set_mode(self.st.cmd_seq, self.st.session_id, mode=mode, auto_controller=auto_controller, flags=flags)
        self._send(pkt)
        self._log(f"[TX] SET_MODE mode={mode.name} seq={self.st.cmd_seq}")
        self.st.cmd_seq += 1

    def send_set_dof(self, cmd: DofCommand, ack_req: bool = False) -> None:
        if not self.st.established or self.st.session_id == 0:
            raise RuntimeError("session not established")
        # 高频 DOF 通常不需要 ACK（否则会压垮链路）；默认 ack_req=False
        flags = FLAG_ACK_REQ if ack_req else 0
        pkt = encode_set_dof(self.st.cmd_seq, self.st.session_id, cmd=cmd, flags=flags)
        self._send(pkt)
        self.st.cmd_seq += 1

    # ----- Heartbeat -----

    def send_heartbeat(self, use_session: bool = True, ack_req: bool = False) -> None:
        sid = self.st.session_id if use_session else 0
        flags = FLAG_ACK_REQ if ack_req else 0
        pkt = encode_heartbeat(self.st.tx_seq, sid, now_ms=int(time.monotonic()*1000), flags=flags, allow_empty=False)
        self._send(pkt)
        self.st.tx_seq += 1
