# src/urogcs/tools/pcap_export.py
from __future__ import annotations

import argparse
import ipaddress
import struct
from dataclasses import dataclass
from typing import Tuple

from urogcs.transport.recorder import iter_records


# ---- PCAP global / packet headers ----
_PCAP_GLOBAL = struct.Struct("<I H H i I I I")  # magic, vmaj, vmin, thiszone, sigfigs, snaplen, network
_PCAP_PKT = struct.Struct("<I I I I")          # ts_sec, ts_usec, incl_len, orig_len

# LINKTYPE_ETHERNET = 1
PCAP_MAGIC = 0xA1B2C3D4


def _ip4_to_u32(ip: str) -> int:
    return int(ipaddress.IPv4Address(ip)) & 0xFFFFFFFF


def _checksum16(data: bytes) -> int:
    # Internet checksum
    if len(data) % 2 == 1:
        data += b"\x00"
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF


def _build_eth_ipv4_udp(
    payload: bytes,
    src_ip: str, src_port: int,
    dst_ip: str, dst_port: int,
) -> bytes:
    # Ethernet (fake MACs)
    dst_mac = b"\xaa\xbb\xcc\xdd\xee\xff"
    src_mac = b"\x11\x22\x33\x44\x55\x66"
    eth_type = b"\x08\x00"  # IPv4
    eth = dst_mac + src_mac + eth_type

    # IPv4 header (no options)
    version_ihl = 0x45
    tos = 0
    total_len = 20 + 8 + len(payload)
    ident = 0
    flags_frag = 0
    ttl = 64
    proto = 17  # UDP
    hdr_cksum = 0
    src_u32 = _ip4_to_u32(src_ip)
    dst_u32 = _ip4_to_u32(dst_ip)

    ip_hdr = struct.pack(
        "!BBHHHBBHII",
        version_ihl,
        tos,
        total_len,
        ident,
        flags_frag,
        ttl,
        proto,
        hdr_cksum,
        src_u32,
        dst_u32,
    )
    ip_cksum = _checksum16(ip_hdr)
    ip_hdr = struct.pack(
        "!BBHHHBBHII",
        version_ihl,
        tos,
        total_len,
        ident,
        flags_frag,
        ttl,
        proto,
        ip_cksum,
        src_u32,
        dst_u32,
    )

    # UDP header (checksum optional; set 0)
    udp_len = 8 + len(payload)
    udp_cksum = 0
    udp_hdr = struct.pack("!HHHH", int(src_port) & 0xFFFF, int(dst_port) & 0xFFFF, udp_len & 0xFFFF, udp_cksum)

    return eth + ip_hdr + udp_hdr + payload


@dataclass
class ExportConfig:
    record_path: str
    out_pcap: str
    gcs_ip: str = "192.168.2.2"
    gcs_port: int = 14551
    rov_ip: str = "192.168.2.3"
    rov_port: int = 14550


def export_pcap(cfg: ExportConfig) -> None:
    snaplen = 65535
    network = 1  # ethernet
    with open(cfg.out_pcap, "wb") as f:
        f.write(_PCAP_GLOBAL.pack(PCAP_MAGIC, 2, 4, 0, 0, snaplen, network))

        written = 0
        for direction, t_ns, payload in iter_records(cfg.record_path):
            # t_ns is monotonic; map to "relative epoch" for Wireshark usability
            ts_sec = int(t_ns // 1_000_000_000)
            ts_usec = int((t_ns % 1_000_000_000) // 1000)

            if direction == "tx":
                frame = _build_eth_ipv4_udp(payload, cfg.gcs_ip, cfg.gcs_port, cfg.rov_ip, cfg.rov_port)
            else:
                frame = _build_eth_ipv4_udp(payload, cfg.rov_ip, cfg.rov_port, cfg.gcs_ip, cfg.gcs_port)

            f.write(_PCAP_PKT.pack(ts_sec, ts_usec, len(frame), len(frame)))
            f.write(frame)
            written += 1

    print(f"[pcap_export] wrote {written} packets -> {cfg.out_pcap}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Export recorder file to PCAP for Wireshark.")
    ap.add_argument("record_path", help="Recorder file path (binary .rec).")
    ap.add_argument("out_pcap", help="Output .pcap file.")
    ap.add_argument("--gcs-ip", default="192.168.2.2")
    ap.add_argument("--gcs-port", type=int, default=14551)
    ap.add_argument("--rov-ip", default="192.168.2.3")
    ap.add_argument("--rov-port", type=int, default=14550)
    args = ap.parse_args()

    cfg = ExportConfig(
        record_path=args.record_path,
        out_pcap=args.out_pcap,
        gcs_ip=args.gcs_ip,
        gcs_port=int(args.gcs_port),
        rov_ip=args.rov_ip,
        rov_port=int(args.rov_port),
    )
    export_pcap(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
