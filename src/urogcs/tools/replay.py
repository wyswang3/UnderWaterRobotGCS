# src/urogcs/tools/replay.py
from __future__ import annotations

import argparse
import socket
import time
from dataclasses import dataclass
from typing import Optional, Literal

from urogcs.transport.recorder import iter_records


Direction = Literal["rx", "tx", "both"]


@dataclass
class ReplayConfig:
    record_path: str
    send_host: str
    send_port: int
    speed: float = 1.0
    direction: Direction = "both"
    loop: bool = False
    max_sleep_s: float = 0.5  # avoid huge sleeps if recording has long gaps


def _should_send(dir_in: str, cfg: ReplayConfig) -> bool:
    if cfg.direction == "both":
        return True
    return dir_in == cfg.direction


def _sleep_scaled(dt_ns: int, speed: float, max_sleep_s: float) -> None:
    if dt_ns <= 0:
        return
    if speed <= 0:
        return
    dt_s = (dt_ns / 1_000_000_000.0) / float(speed)
    if dt_s <= 0:
        return
    if dt_s > max_sleep_s:
        dt_s = max_sleep_s
    time.sleep(dt_s)


def replay_once(cfg: ReplayConfig) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (cfg.send_host, int(cfg.send_port))

    last_t_ns: Optional[int] = None
    sent = 0
    bytes_sent = 0

    t0_wall = time.time()
    try:
        for direction, t_ns, payload in iter_records(cfg.record_path):
            if not _should_send(direction, cfg):
                continue

            if last_t_ns is None:
                last_t_ns = t_ns
            else:
                _sleep_scaled(int(t_ns - last_t_ns), cfg.speed, cfg.max_sleep_s)
                last_t_ns = t_ns

            if payload:
                sock.sendto(payload, target)
                sent += 1
                bytes_sent += len(payload)
    finally:
        sock.close()

    dt = time.time() - t0_wall
    print(f"[replay] done: pkts={sent} bytes={bytes_sent} wall={dt:.2f}s speed={cfg.speed}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Replay recorded packets to UDP endpoint.")
    ap.add_argument("record_path", help="Path to recorder file (binary .rec).")
    ap.add_argument("--to-ip", default="127.0.0.1", help="Destination IP.")
    ap.add_argument("--to-port", type=int, default=14550, help="Destination UDP port.")
    ap.add_argument("--speed", type=float, default=1.0, help="Replay speed factor (1.0=real-time).")
    ap.add_argument("--dir", choices=["rx", "tx", "both"], default="both", help="Replay direction filter.")
    ap.add_argument("--loop", action="store_true", help="Loop replay.")
    args = ap.parse_args()

    cfg = ReplayConfig(
        record_path=args.record_path,
        send_host=args.to_ip,
        send_port=args.to_port,
        speed=float(args.speed),
        direction=args.dir,
        loop=bool(args.loop),
    )

    while True:
        replay_once(cfg)
        if not cfg.loop:
            break
        time.sleep(0.2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
