#!/usr/bin/env python3
from __future__ import annotations

import argparse
import mmap
import os
import struct
import time

# 你的 server 输出已经明确：
# shm_name=/rovctrl_gcs_intent_v1, size=136
DEFAULT_SHM_NAME = "/rovctrl_gcs_intent_v1"
DEFAULT_SIZE = 136

# ====== 按你给的 C++ ControlIntent 结构做一个“最小可用”解析 ======
# 注意：这份解析依赖“典型 ABI 布局 + padding”，用于调试足够好。
# 若你后面要完全严谨，我们可以用 C++ 写一个 dump 工具，或在 Python 端用 ctypes.Structure 精确对齐。

# 结构开头字段（根据你贴的定义）
# u32 version, u32 flags, u64 seq, u64 stamp_ns, u32 ttl_ms
_HDR0 = struct.Struct("<I I Q Q I")

# 之后：request_exit(u8), estop(u8), clear_estop(u8), arm(u8), disarm(u8), pad0(u8), pad1(u8), pad2(u8)
_HDR1 = struct.Struct("<8B")

# mode_request: u8 + pad3[7]
_MODE = struct.Struct("<B 7s")

# DofCommand: 6 doubles
_DOF = struct.Struct("<6d")

# 后面 reserved0 u32 reserved1 u32
_TAIL = struct.Struct("<I I")


def parse_control_intent(buf: bytes) -> dict:
    off = 0
    version, flags, seq, stamp_ns, ttl_ms = _HDR0.unpack_from(buf, off)
    off += _HDR0.size

    (request_exit, estop, clear_estop,
     arm, disarm, pad0, pad1, pad2) = _HDR1.unpack_from(buf, off)
    off += _HDR1.size

    mode_request, _pad3 = _MODE.unpack_from(buf, off)
    off += _MODE.size

    surge, sway, heave, roll, pitch, yaw = _DOF.unpack_from(buf, off)
    off += _DOF.size

    reserved0, reserved1 = _TAIL.unpack_from(buf, off)
    off += _TAIL.size

    return {
        "version": version,
        "flags": flags,
        "seq": seq,
        "stamp_ns": stamp_ns,
        "ttl_ms": ttl_ms,
        "request_exit": request_exit,
        "estop": estop,
        "clear_estop": clear_estop,
        "arm": arm,
        "disarm": disarm,
        "mode_request": mode_request,
        "dof": (surge, sway, heave, roll, pitch, yaw),
        "reserved0": reserved0,
        "reserved1": reserved1,
        "bytes_used": off,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shm", default=DEFAULT_SHM_NAME)
    ap.add_argument("--size", type=int, default=DEFAULT_SIZE)
    ap.add_argument("--hz", type=float, default=10.0)
    args = ap.parse_args()

    path = f"/dev/shm{args.shm}"
    if not os.path.exists(path):
        print(f"[ERR] shm file not found: {path}")
        print("      请先启动 gcs_server，并确认 shm_name 一致。")
        return 2

    fd = os.open(path, os.O_RDONLY)
    try:
        mm = mmap.mmap(fd, args.size, access=mmap.ACCESS_READ)
        period = 1.0 / max(1e-6, args.hz)
        last_seq = None
        print(f"[WATCH] {path} size={args.size} hz={args.hz}")
        while True:
            mm.seek(0)
            data = mm.read(args.size)
            it = parse_control_intent(data)

            seq = it["seq"]
            if last_seq != seq:
                last_seq = seq
                dof = it["dof"]
                print(
                    f"[INTENT] seq={seq} ttl_ms={it['ttl_ms']} flags=0x{it['flags']:08x} "
                    f"estop={it['estop']} mode={it['mode_request']} "
                    f"dof=({dof[0]:+.3f},{dof[1]:+.3f},{dof[2]:+.3f},{dof[3]:+.3f},{dof[4]:+.3f},{dof[5]:+.3f})"
                )

            time.sleep(period)
    finally:
        try:
            os.close(fd)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
