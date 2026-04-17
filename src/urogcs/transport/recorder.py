"""Raw packet recorder for GCS-side transport debugging and replay.

作用：
- 以紧凑二进制格式记录 GCS 收发的原始 UDP payload；
- 为 replay、pcap 导出和现场问题复盘保留最小原始证据。

实现思路：
- 记录器不理解业务协议，只按方向、时间戳和 payload 原样落盘；
- 回放和分析工具在后续阶段复用同一文件格式，避免多套抓包格式并存。
"""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Literal


Direction = Literal["rx", "tx"]

_MAGIC = 0x47524331  # "GRC1"
_HDR = struct.Struct("<I B B H Q I")  # magic,u8dir,u8r,u16r,u64t,u32n


@dataclass
class RecorderStats:
    records: int = 0
    bytes: int = 0


class PacketRecorder:
    """
    Binary packet recorder for raw UDP payloads (GCS side).
    Designed for debugging + replay.

    - call record_rx(data) and record_tx(data)
    - close() on exit
    """
    def __init__(self, path: str | os.PathLike, enabled: bool = True) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self._fh: Optional[object] = None
        self.stats = RecorderStats()

        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "ab", buffering=0)

    def close(self) -> None:
        try:
            if self._fh:
                self._fh.close()
        finally:
            self._fh = None

    def _write(self, direction: Direction, data: bytes) -> None:
        if not self.enabled or not self._fh:
            return
        if data is None:
            return
        b = bytes(data)

        dir_u8 = 0 if direction == "rx" else 1
        t_ns = time.monotonic_ns() & 0xFFFFFFFFFFFFFFFF
        n = len(b) & 0xFFFFFFFF

        header = _HDR.pack(_MAGIC, dir_u8, 0, 0, t_ns, n)
        self._fh.write(header)
        if n > 0:
            self._fh.write(b)

        self.stats.records += 1
        self.stats.bytes += len(header) + len(b)

    def record_rx(self, data: bytes) -> None:
        self._write("rx", data)

    def record_tx(self, data: bytes) -> None:
        self._write("tx", data)


def iter_records(path: str | os.PathLike):
    """
    Generator to iterate recorded packets:
      yields (direction:str, t_ns:int, payload:bytes)
    """
    p = Path(path)
    with open(p, "rb") as f:
        while True:
            h = f.read(_HDR.size)
            if not h:
                return
            if len(h) != _HDR.size:
                return
            magic, dir_u8, _r0, _r1, t_ns, n = _HDR.unpack(h)
            if magic != _MAGIC:
                # Stop on desync
                return
            payload = f.read(int(n))
            if len(payload) != int(n):
                return
            direction = "rx" if dir_u8 == 0 else "tx"
            yield direction, int(t_ns), payload
