from __future__ import annotations

"""
urogcs.session.session_client

面向 ROV 的 GCS UDP 会话客户端（Python 侧）：

- 负责底层 UDP 收发；
- 实现 CONNECT_REQ / CONNECT_ACK / CONNECT_CONFIRM 三步握手；
- 解析 STATUS / ACK 报文，维护会话状态；
- 提供 send_* 系列方法发送 ESTOP / MODE / DOF / ARM 等控制指令。

上层（例如 service.py / TUI）应尽量只依赖：
    - handshake()
    - poll()
    - send_heartbeat()
    - send_set_mode() / send_set_dof() / send_estop() / send_arm()
    - state / last_status 属性
"""

import os
import socket
import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from urogcs.protocol.codec import (
    parse_and_validate,
    decode_connect_ack,
    decode_status,
    decode_ack,          # decode_ack(hdr, payload) -> (ack_seq, ack_code_u16, reason)
    encode_connect_req,
    encode_connect_confirm,
    encode_heartbeat,
    encode_set_mode,
    encode_set_dof,
    encode_estop,
    encode_arm,          # ARM / DISARM
)
from urogcs.protocol.wire import (
    MsgType,
    AckCode,
    Flags,
    WireControlMode,
)
from urogcs.protocol.messages import DofCommand, StatusTelemetry


# =============================================================================
# Debug logger 配置
# =============================================================================

@dataclass
class DebugConfig:
    enabled: bool = False          # 全局开关
    rx_hex: bool = False           # 打印收到的包十六进制
    tx_hex: bool = False           # 打印发送包十六进制
    max_hex_bytes: int = 96        # hex 打印截断长度
    verbose_poll: bool = False     # poll 时每包打印一行详情


def _hexdump(b: bytes, max_len: int = 96) -> str:
    """将二进制数据格式化为十六进制字符串（用于调试日志）."""
    if not b:
        return ""
    bb = b[:max_len]
    s = " ".join(f"{x:02x}" for x in bb)
    if len(b) > max_len:
        s += f" ...(+{len(b) - max_len})"
    return s


# =============================================================================
# 会话状态与握手配置
# =============================================================================

@dataclass
class SessionState:
    """GCS 客户端会话状态（简单版本，供上层只读使用）."""

    established: bool = False      # 是否已完成握手
    session_id: int = 0

    gcs_nonce: int = 0
    rov_nonce: int = 0

    # sequencing
    tx_seq: int = 1                # wire header.seq for client->server packets
    cmd_seq: int = 1               # 预留：如果后续需要独立命令序号


@dataclass
class HandshakeConfig:
    """握手流程参数配置."""

    timeout_s: float = 2.0                # CONNECT_ACK 等待超时
    confirm_ack_timeout_s: float = 2.0    # CONNECT_CONFIRM 的 ACK 等待超时
    rx_poll_max_packets: int = 32         # 进入第二阶段时每轮 poll 的最大包数
    require_confirm_ack: bool = True      # 是否必须收到 CONFIRM 的 ACK
    allow_status_established: bool = True # 是否允许通过 STATUS 中的标志判定已建立
    debug: bool = False                   # 打开后打印更详细的握手日志


# =============================================================================
# Client 实现
# =============================================================================

class GcsSessionClient:
    """
    GCS 会话客户端（底层 UDP + 协议封装）.

    职责：
      - 管理 UDP socket 与目标 ROV 地址；
      - 实现握手流程（handshake）；
      - 解析 STATUS / ACK 等消息，更新内部 SessionState 与 last_status；
      - 提供 send_* 系列 API 供上层发送控制命令；
      - 提供 poll() 供上层在主循环中调用。
    """

    def __init__(
        self,
        rov_addr: Tuple[str, int],
        bind_addr: Tuple[str, int] = ("0.0.0.0", 14551),
        recv_timeout_ms: int = 20,
        on_status: Optional[Callable[[StatusTelemetry], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        debug: Optional[bool] = None,  # 若为 None，则参考环境变量 UROGCS_DEBUG
    ) -> None:
        self.rov_addr = rov_addr
        self.bind_addr = bind_addr
        self.recv_timeout_ms = int(recv_timeout_ms)

        self.on_status = on_status
        self.on_log = on_log

        # -------- Debug 开关初始化 --------
        env_dbg = os.getenv("UROGCS_DEBUG", "0").strip() not in ("0", "", "false", "False")
        dbg_enabled = env_dbg if debug is None else bool(debug)
        self.dbg = DebugConfig(enabled=dbg_enabled)

        # 更细粒度的环境变量开关
        self.dbg.rx_hex = os.getenv("UROGCS_DEBUG_RX_HEX", "0") == "1"
        self.dbg.tx_hex = os.getenv("UROGCS_DEBUG_TX_HEX", "0") == "1"
        self.dbg.verbose_poll = os.getenv("UROGCS_DEBUG_VERBOSE_POLL", "0") == "1"
        try:
            self.dbg.max_hex_bytes = int(os.getenv("UROGCS_DEBUG_MAX_HEX", str(self.dbg.max_hex_bytes)))
        except Exception:
            pass

        # -------- UDP socket 初始化 --------
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Note: GUI may pass bind_port=0 (ephemeral) so it can coexist with the TUI.
        # We still want rapid restarts to work during bench bring-up.
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass

        self.sock.bind(self.bind_addr)
        # If bind_port=0, the OS picks an ephemeral port; capture the real bound tuple for logs/UX.
        try:
            host, port = self.sock.getsockname()[:2]
            self.bind_addr = (str(host), int(port))
        except OSError:
            pass
        self.sock.settimeout(max(0.001, self.recv_timeout_ms / 1000.0))

        # 会话状态
        self.st = SessionState()

        self.last_error: str = ""
        self._last_status: Optional[StatusTelemetry] = None

        # 握手 / 命令 ACK 跟踪
        self._pending_ack_seq: Optional[int] = None
        self._pending_ack_code: Optional[AckCode] = None
        self._pending_ack_reason: Optional[int] = None
        self._pending_ack_kind: str = ""
        self._last_tx_seq: Optional[int] = None
        self._last_tx_kind: str = ""
        self._last_tx_time_ns: int = 0
        self._last_ack_seq: Optional[int] = None
        self._last_ack_code: Optional[AckCode] = None
        self._last_ack_reason: Optional[int] = None
        self._last_ack_kind: str = ""

        self._log(
            f"[INIT] bind={self.bind_addr[0]}:{self.bind_addr[1]} "
            f"target={self.rov_addr[0]}:{self.rov_addr[1]}"
        )
        if self.dbg.enabled:
            self._log(
                f"[DBG] enabled=1 rx_hex={int(self.dbg.rx_hex)} "
                f"tx_hex={int(self.dbg.tx_hex)} verbose_poll={int(self.dbg.verbose_poll)}"
            )

    # -------------------------------------------------------------------------
    # 属性访问（建议上层通过 property 读取）
    # -------------------------------------------------------------------------

    @property
    def state(self) -> SessionState:
        """
        当前会话状态（只读快照）.

        注意：这是对 self.st 的浅引用，外层请视作只读，不要修改字段。
        """
        return self.st

    @property
    def last_status(self) -> Optional[StatusTelemetry]:
        """最近一次收到并成功 decode 的 STATUS 报文."""
        return self._last_status

    @property
    def last_tx_seq(self) -> Optional[int]:
        return self._last_tx_seq

    @property
    def last_tx_kind(self) -> str:
        return self._last_tx_kind

    @property
    def last_tx_time_ns(self) -> int:
        return self._last_tx_time_ns

    @property
    def waiting_ack(self) -> bool:
        return self._pending_ack_seq is not None and self._pending_ack_code is None

    @property
    def pending_ack_seq(self) -> Optional[int]:
        return self._pending_ack_seq if self.waiting_ack else None

    @property
    def pending_ack_kind(self) -> str:
        return self._pending_ack_kind if self.waiting_ack else ""

    @property
    def last_ack_seq(self) -> Optional[int]:
        return self._last_ack_seq

    @property
    def last_ack_kind(self) -> str:
        return self._last_ack_kind

    @property
    def last_ack_code(self) -> Optional[int]:
        return int(self._last_ack_code) if self._last_ack_code is not None else None

    @property
    def last_ack_reason(self) -> Optional[int]:
        return self._last_ack_reason

    # -------------------------------------------------------------------------
    # logging helpers
    # -------------------------------------------------------------------------

    def _log(self, s: str) -> None:
        """
        统一日志入口：
          - 若上层提供 on_log，则优先调用；
          - 若 debug.enabled，则也打印到 stdout 方便调试。
        """
        if self.on_log:
            try:
                self.on_log(s)
            except Exception:
                # 保底不影响主流程
                pass
        if self.dbg.enabled:
            print(s, flush=True)

    def _set_err(self, s: str) -> None:
        """记录并打印错误（会更新 last_error）."""
        self.last_error = s
        self._log(s)

    def _record_command_tx(self, kind: str, seq: int) -> None:
        """
        Track the latest operator-visible command transmission.

        This intentionally excludes heartbeats to keep UI feedback aligned with
        discrete operator actions such as ESTOP / ARM / SET_MODE.
        """
        self._last_tx_seq = int(seq)
        self._last_tx_kind = kind
        self._last_tx_time_ns = time.monotonic_ns()

    # -------------------------------------------------------------------------
    # transport
    # -------------------------------------------------------------------------

    def close(self) -> None:
        """关闭底层 UDP socket."""
        try:
            self.sock.close()
        except Exception:
            pass

    def _send(self, pkt: bytes) -> None:
        """封装 sendto + 可选 TX 调试输出."""
        if self.dbg.enabled:
            self._log(f"[TX] -> {self.rov_addr} bytes={len(pkt)}")
            if self.dbg.tx_hex:
                self._log(f"[TX_HEX] {_hexdump(pkt, self.dbg.max_hex_bytes)}")
        self.sock.sendto(pkt, self.rov_addr)

    def _recv_once(self) -> Optional[Tuple[bytes, Tuple[str, int]]]:
        """尝试接收一帧 UDP 数据，失败或超时返回 None."""
        try:
            data, addr = self.sock.recvfrom(2048)
            if self.dbg.enabled:
                self._log(f"[RX] <- {addr} bytes={len(data)}")
                if self.dbg.rx_hex:
                    self._log(f"[RX_HEX] {_hexdump(data, self.dbg.max_hex_bytes)}")
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
        """处理 CONNECT_ACK，验证 nonce / session_id，并更新 state."""
        try:
            gcs_nonce_echo, rov_nonce, rov_caps, result_code = decode_connect_ack(payload)
        except Exception as e:
            self._log(f"[HS] CONNECT_ACK decode error: {e}")
            return False

        if result_code != 0:
            self._log(f"[HS] CONNECT_ACK result_code={result_code} (reject)")
            return False

        if gcs_nonce_echo != self.st.gcs_nonce:
            self._log(
                f"[HS] CONNECT_ACK nonce mismatch: echo={gcs_nonce_echo} "
                f"expected={self.st.gcs_nonce}"
            )
            return False

        if session_id == 0 or rov_nonce == 0:
            self._log(f"[HS] CONNECT_ACK invalid: session_id={session_id} rov_nonce={rov_nonce}")
            return False

        self.st.session_id = int(session_id)
        self.st.rov_nonce = int(rov_nonce)

        self._log(
            f"[HS] got CONNECT_ACK session_id={self.st.session_id} "
            f"rov_nonce={self.st.rov_nonce} caps={rov_caps}"
        )
        return True

    def _handle_ack(self, hdr, payload: bytes) -> None:
        """
        ACK 报文处理逻辑：

        协议约定：
          - hdr.ack_seq 是被确认的 seq；
          - payload 为 4 字节：u16 ack_code, u16 reason。
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
            self._last_ack_seq = int(ack_seq)
            self._last_ack_code = code
            self._last_ack_reason = int(reason)
            self._last_ack_kind = self._pending_ack_kind
            self._log(f"[RX][ACK] matched pending ack_seq={ack_seq} code={code.name}")

    def _status_indicates_established(self) -> bool:
        """从最近 STATUS 中判断是否已建立会话（session_established=1）."""
        st = self._last_status
        if not st:
            return False
        return int(st.session_established) == 1

    # -------------------------------------------------------------------------
    # poll
    # -------------------------------------------------------------------------

    def poll(self, max_packets: int = 16) -> None:
        """
        从 UDP 中拉取最多 max_packets 个数据包，解析并分发处理。

        - STATUS      -> decode_status() 更新 self._last_status 并调用 on_status；
        - ACK         -> 交给 _handle_ack() 处理 pending ack；
        - 其它类型    -> 目前忽略（必要时再扩展）。
        """
        for _ in range(max_packets):
            rx = self._recv_once()
            if not rx:
                return
            data, addr = rx

            pp, code, err = parse_and_validate(data)
            if not pp:
                # 这条日志是目前排查 ACK/STATUS 丢包的关键信息
                self._log(
                    f"[RX] parse failed: {code.name} {err} "
                    f"from {addr} len={len(data)}"
                )
                continue

            mt = MsgType(pp.hdr.msg_type)

            if self.dbg.enabled and self.dbg.verbose_poll:
                self._log(
                    "[RX] parsed "
                    f"mt={mt.name} seq={pp.hdr.seq} sid={pp.hdr.session_id} "
                    f"flags=0x{pp.hdr.flags:04x} plen={pp.hdr.payload_len} "
                    f"ack_seq={pp.hdr.ack_seq}"
                )

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

            # 其他类型目前忽略，后续需要时再扩展
            # self._log(f"[RX] ignore mt={mt.name}")

    # -------------------------------------------------------------------------
    # handshake
    # -------------------------------------------------------------------------

    def handshake(self, timeout_s: float = 2.0,
                  hs_cfg: Optional[HandshakeConfig] = None) -> bool:
        """
        可靠握手流程：

          1) 发送 CONNECT_REQ；
          2) 等待 CONNECT_ACK，验证 nonce / session_id / rov_nonce；
          3) 发送带 ACK_REQ 的 CONNECT_CONFIRM；
          4) 等待：
              - CONFIRM 对应的 ACK（require_confirm_ack=True），或
              - STATUS 中的 session_established=1（allow_status_established=True）。

        返回：
          - True  表示握手成功，st.established 会被置为 True；
          - False 表示握手失败，可查看 last_error。
        """
        cfg = hs_cfg or HandshakeConfig(timeout_s=timeout_s)
        if self.dbg.enabled:
            cfg.debug = True  # 调试模式自动打开握手日志

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
        self._pending_ack_kind = ""
        self._last_status = None
        self._last_tx_seq = None
        self._last_tx_kind = ""
        self._last_tx_time_ns = 0
        self._last_ack_seq = None
        self._last_ack_code = None
        self._last_ack_reason = None
        self._last_ack_kind = ""

        # client nonce
        self.st.gcs_nonce = int.from_bytes(os.urandom(8), "little")

        # ---- 1) send CONNECT_REQ ----
        req_seq = self.st.tx_seq
        pkt = encode_connect_req(
            seq=req_seq,
            gcs_nonce=self.st.gcs_nonce,
            flags=Flags(0),
        )
        self._send(pkt)
        self._log(f"[HS] sent CONNECT_REQ seq={req_seq} gcs_nonce={self.st.gcs_nonce}")
        self.st.tx_seq += 1

        # ---- 2) wait CONNECT_ACK ----
        t0 = time.time()
        got_connect_ack = False

        while time.time() - t0 < cfg.timeout_s:
            rx = self._recv_once()
            if not rx:
                continue
            data, addr = rx

            pp, code, err = parse_and_validate(data)
            if not pp:
                self._log(
                    f"[HS] parse failed: {code.name} {err} "
                    f"from {addr} len={len(data)}"
                )
                continue

            mt = MsgType(pp.hdr.msg_type)

            if cfg.debug:
                self._log(
                    "[HS][DBG] "
                    f"mt={mt.name} seq={pp.hdr.seq} sid={pp.hdr.session_id} "
                    f"flags=0x{pp.hdr.flags:04x} plen={pp.hdr.payload_len} "
                    f"ack_seq={pp.hdr.ack_seq}"
                )

            if mt == MsgType.CONNECT_ACK:
                got_connect_ack = self._handle_connect_ack(
                    pp.hdr.session_id,
                    pp.payload,
                    debug=cfg.debug,
                )
                if got_connect_ack:
                    break
                continue

            # 允许在握手阶段同时收到 STATUS / ACK（不作为错误）
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
                self._handle_ack(pp.hdr, pp.payload)
                continue

        if not got_connect_ack:
            self._set_err("[HS] CONNECT_ACK timeout")
            return False

        if self.st.session_id == 0 or self.st.rov_nonce == 0:
            self._set_err(
                f"[HS] invalid session params: "
                f"session_id={self.st.session_id} rov_nonce={self.st.rov_nonce}"
            )
            return False

        # ---- 3) send CONNECT_CONFIRM with ACK_REQ ----
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
        self._pending_ack_kind = "CONNECT_CONFIRM"

        self._send(pkt2)
        self._log(
            f"[HS] sent CONNECT_CONFIRM seq={confirm_seq} "
            f"session_id={self.st.session_id}"
        )
        self.st.tx_seq += 1

        # ---- 4) wait confirm ACK or STATUS established ----
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

                self._set_err(
                    "[HS] CONNECT_CONFIRM rejected: "
                    f"{self._pending_ack_code.name} "
                    f"reason={self._pending_ack_reason}"
                )
                return False

            time.sleep(0.005)

        if cfg.require_confirm_ack:
            self._set_err("[HS] CONNECT_CONFIRM ACK timeout")
            return False

        # 乐观模式：即便没收到 ACK，也认为 established
        self.st.established = True
        self._log("[HS] established (optimistic)")
        return True

    # -------------------------------------------------------------------------
    # command send APIs
    # -------------------------------------------------------------------------

    def send_heartbeat(self, use_session: bool = True, ack_req: bool = False) -> None:
        """发送心跳包，可选是否带 session_id / ACK_REQ."""
        sid = self.st.session_id if use_session else 0
        flags = Flags.ACK_REQ if ack_req else Flags(0)
        now_ms = int(time.monotonic() * 1000) & 0xFFFFFFFF
        pkt = encode_heartbeat(
            seq=self.st.tx_seq,
            session_id=sid,
            now_ms=now_ms,
            flags=flags,
        )
        self._send(pkt)
        self.st.tx_seq += 1

    def send_set_mode(
        self,
        mode: WireControlMode,
        auto_controller: str = "",
        ack_req: bool = True,
    ) -> None:
        """
        发送 SET_MODE 命令（底层接口）.

        建议在 service 层封装为 request_mode() 再给 TUI 使用。
        """
        flags = Flags.ACK_REQ if ack_req else Flags(0)
        pkt = encode_set_mode(
            seq=self.st.tx_seq,
            session_id=self.st.session_id,
            mode=mode,
            auto_controller=auto_controller,
            flags=flags,
        )
        self._record_command_tx("SET_MODE", self.st.tx_seq)
        if ack_req:
            self._pending_ack_seq = self.st.tx_seq
            self._pending_ack_code = None
            self._pending_ack_reason = None
            self._pending_ack_kind = "SET_MODE"

        self._send(pkt)
        self.st.tx_seq += 1

    # 兼容性别名：后续可以让上层调用 send_mode()，内部转发到 send_set_mode()
    def send_mode(
        self,
        mode: WireControlMode,
        auto_controller: str = "",
        ack_req: bool = True,
    ) -> None:
        """兼容别名：内部直接调用 send_set_mode()."""
        self.send_set_mode(mode=mode, auto_controller=auto_controller, ack_req=ack_req)

    def send_set_dof(self, cmd: DofCommand, ack_req: bool = False) -> None:
        """
        发送高频 SET_DOF 命令（底层接口）.

        一般不需要 ACK_REQ，避免 ACK 带来额外开销。
        """
        flags = Flags.ACK_REQ if ack_req else Flags(0)
        pkt = encode_set_dof(
            seq=self.st.tx_seq,
            session_id=self.st.session_id,
            cmd=cmd,
            flags=flags,
        )
        if ack_req:
            self._pending_ack_seq = self.st.tx_seq
            self._pending_ack_code = None
            self._pending_ack_reason = None
            self._pending_ack_kind = "SET_DOF"

        self._send(pkt)
        self.st.tx_seq += 1

    # 兼容性别名：send_dof() -> send_set_dof()
    def send_dof(self, cmd: DofCommand, ack_req: bool = False) -> None:
        """兼容别名：内部直接调用 send_set_dof()."""
        self.send_set_dof(cmd=cmd, ack_req=ack_req)

    def send_estop(self, enable: bool, ack_req: bool = True) -> None:
        """
        发送 ESTOP 命令（带/不带 ACK_REQ）.

        建议上层统一通过 service.request_estop() 调用。
        """
        flags = Flags.ACK_REQ if ack_req else Flags(0)
        pkt = encode_estop(
            seq=self.st.tx_seq,
            session_id=self.st.session_id,
            enable=enable,
            flags=flags,
        )
        self._record_command_tx("ESTOP", self.st.tx_seq)
        if ack_req:
            self._pending_ack_seq = self.st.tx_seq
            self._pending_ack_code = None
            self._pending_ack_reason = None
            self._pending_ack_kind = "ESTOP"

        self._send(pkt)
        self.st.tx_seq += 1

    def send_arm(self, armed: bool, ack_req: bool = True) -> None:
        """
        低层 ARM / DISARM 发送接口：
          - armed=True  => 请求解锁
          - armed=False => 请求上锁
        """
        flags = Flags.ACK_REQ if ack_req else Flags(0)
        pkt = encode_arm(
            seq=self.st.tx_seq,
            session_id=self.st.session_id,
            armed=armed,
            flags=flags,
        )
        self._record_command_tx("ARM", self.st.tx_seq)
        if ack_req:
            self._pending_ack_seq = self.st.tx_seq
            self._pending_ack_code = None
            self._pending_ack_reason = None
            self._pending_ack_kind = "ARM"

        self._send(pkt)
        self._log(f"[GCS] send_arm armed={int(armed)} seq={self.st.tx_seq}")
        self.st.tx_seq += 1

    # 兼容上层旧调用：request_arm() -> send_arm()
    def request_arm(self, armed: bool, ack_req: bool = True) -> None:
        """
        上层友好别名（历史原因保留）：

          - 未来建议在 service.py 中实现 GcsService.request_arm()，
            并让 TUI 仅依赖 service 层；
          - 这里先保留别名以避免立即破坏现有调用。
        """
        self.send_arm(armed=armed, ack_req=ack_req)
