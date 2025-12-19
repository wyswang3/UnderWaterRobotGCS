# src/urogcs/transport/udp_link.py
from __future__ import annotations

import socket
import time
import select
from dataclasses import dataclass
from typing import Optional, Tuple, List
from urogcs.transport.recorder import PacketRecorder



Addr = Tuple[str, int]


@dataclass(frozen=True)
class UdpEndpoint:
    host: str
    port: int

    def as_tuple(self) -> Addr:
        return (self.host, self.port)


class UdpLink:
    """
    Thin UDP transport.

    - send_to: default remote endpoint (vehicle comm_gcs)
    - bind: local bind for receiving telemetry (GCS side)
    - non-blocking socket + select-based timeout receive
    """

    def __init__(
        self,
        send_to: UdpEndpoint,
        bind: Optional[UdpEndpoint] = None,
        recv_buf: int = 64 * 1024,
        reuse_addr: bool = True,
    ) -> None:
        self.recorder = PacketRecorder()
        self.send_to = send_to
        self.bind = bind
        self.recv_buf = int(recv_buf)

        self.sock: Optional[socket.socket] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Reuse address helps rapid restart during dev
        if reuse_addr:
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except OSError:
                pass

        # Non-blocking; we use select() for waits
        self.sock.setblocking(False)

        if bind is not None:
            self.sock.bind(bind.as_tuple())

        # Stats
        self.last_rx_ns: int = 0
        self.rx_packets: int = 0
        self.rx_bytes: int = 0
        self.tx_packets: int = 0
        self.tx_bytes: int = 0

        # Error observability
        self.last_tx_err: Optional[str] = None
        self.last_rx_err: Optional[str] = None

    def close(self) -> None:
        s = self.sock
        self.sock = None
        if s is None:
            return
        try:
            s.close()
        except Exception:
            pass

    def send(self, data: bytes, to: Optional[UdpEndpoint] = None) -> bool:
        """
        Send datagram. Returns True on success, False on failure (error in last_tx_err).
        """
        s = self.sock
        if s is None:
            self.last_tx_err = "socket closed"
            return False        
        
        if self.recorder:
            self.recorder.record_tx(data)
            n = self.sock.sendto(data, self.send_to.as_tuple())

        dst = (to or self.send_to).as_tuple()
        try:
            n = s.sendto(data, dst)
            self.tx_packets += 1
            self.tx_bytes += int(n)
            self.last_tx_err = None
            return True
        except OSError as e:
            self.last_tx_err = f"{type(e).__name__}: {e}"
            return False

    def recv(self, timeout_ms: int = 0) -> Optional[Tuple[bytes, Addr]]:
        """
        Receive one datagram.
        - timeout_ms=0 : poll once
        - timeout_ms>0 : wait up to timeout using select()

        Returns (data, addr) or None.
        """
        s = self.sock
        if s is None:
            self.last_rx_err = "socket closed"
            return None

        # Wait for readability if requested
        if timeout_ms > 0:
            timeout_s = timeout_ms / 1000.0
            try:
                r, _w, _x = select.select([s], [], [], timeout_s)
                if not r:
                    return None
            except OSError as e:
                self.last_rx_err = f"{type(e).__name__}: {e}"
                return None

        try:
            data, addr = s.recvfrom(self.recv_buf)
            if self.recorder:
             self.recorder.record_rx(data)
            now_ns = time.monotonic_ns()
            self.last_rx_ns = now_ns
            self.rx_packets += 1
            self.rx_bytes += len(data)
            self.last_rx_err = None
            return data, (addr[0], int(addr[1]))
        except BlockingIOError:
            return None
        except OSError as e:
            self.last_rx_err = f"{type(e).__name__}: {e}"
            return None
        

    def drain(self, max_packets: int = 64) -> List[Tuple[bytes, Addr]]:
        """
        Drain all currently available datagrams up to max_packets.
        Useful to avoid STATUS backlog in UI tick.
        """
        out: List[Tuple[bytes, Addr]] = []
        for _ in range(max_packets):
            item = self.recv(timeout_ms=0)
            if item is None:
                break
            out.append(item)
        return out

    def link_age_ms(self) -> Optional[float]:
        if self.last_rx_ns == 0:
            return None
        return (time.monotonic_ns() - self.last_rx_ns) / 1_000_000.0
