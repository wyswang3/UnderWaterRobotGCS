# src/urogcs/protocol/crc32c.py
from __future__ import annotations

from typing import Optional

_TABLE: Optional[list[int]] = None

def _init_table() -> list[int]:
    global _TABLE
    if _TABLE is not None:
        return _TABLE
    poly = 0x82F63B78
    t: list[int] = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (poly ^ (c >> 1)) if (c & 1) else (c >> 1)
        t.append(c & 0xFFFFFFFF)
    _TABLE = t
    return t

def crc32c(data: Optional[bytes]) -> int:
    # Match C++:
    # if (!data || len==0) return 0;
    if not data:
        return 0
    table = _init_table()
    crc = 0xFFFFFFFF
    for b in data:
        crc = table[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF
