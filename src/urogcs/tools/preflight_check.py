#!/usr/bin/env python3
from __future__ import annotations

import argparse
import socket
import sys
from dataclasses import dataclass

from urogcs.app.tui.tui_env import TuiConfig


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    title: str
    detail: str


def _resolve_target(host: str, port: int) -> PreflightResult:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
    except OSError as exc:
        return PreflightResult(False, 'target_resolve', f'cannot resolve {host}:{port} ({exc})')

    families = sorted({info[0] for info in infos})
    return PreflightResult(True, 'target_resolve', f'{host}:{port} resolved via families={families}')


def _probe_bind(bind_ip: str, bind_port: int) -> PreflightResult:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((bind_ip, bind_port))
    except OSError as exc:
        return PreflightResult(False, 'bind_port', f'cannot bind {bind_ip}:{bind_port} ({exc})')
    finally:
        sock.close()
    return PreflightResult(True, 'bind_port', f'local UDP bind {bind_ip}:{bind_port} is available')


def _python_runtime_check() -> PreflightResult:
    if sys.version_info < (3, 10):
        return PreflightResult(False, 'python', f'Python {sys.version.split()[0]} is too old; require >= 3.10')
    return PreflightResult(True, 'python', f'Python {sys.version.split()[0]}')


def _platform_check() -> PreflightResult:
    if sys.platform.startswith('win'):
        return PreflightResult(
            True,
            'platform',
            'Windows minimal path enabled: telemetry/diagnostics are supported; keyboard teleop remains POSIX-only.',
        )
    return PreflightResult(True, 'platform', 'POSIX path enabled: keyboard TUI and telemetry diagnostics are available.')


def run_preflight(cfg: TuiConfig, *, bind_check: bool = True) -> int:
    results = [
        _python_runtime_check(),
        _platform_check(),
        _resolve_target(cfg.rov_ip, cfg.rov_port),
    ]
    if bind_check:
        results.append(_probe_bind(cfg.bind_ip, cfg.bind_port))

    print('')
    print('============================================')
    print(' UnderWaterRobotGCS - Preflight Check')
    print('============================================')
    print(f'[INFO] target={cfg.rov_ip}:{cfg.rov_port} bind={cfg.bind_ip}:{cfg.bind_port}')
    print('')

    failures = 0
    for item in results:
        prefix = '[ OK ]' if item.ok else '[ERR]'
        print(f'{prefix} {item.title}: {item.detail}')
        if not item.ok:
            failures += 1

    print('')
    print('[NEXT] ROV side order: uwnav_navd -> nav_viewd -> gcs_server -> pwm_control_program')
    print('[NEXT] Operator side: run scripts/run_gui.sh, scripts/run_gui.ps1, or the existing TUI entry after preflight passes')
    if sys.platform.startswith('win'):
        print('[NEXT] Windows GUI is a first-stage preview; keyboard teleop still remains outside the current supported path.')

    return 0 if failures == 0 else 1


def main() -> int:
    base_cfg = TuiConfig.from_env()

    ap = argparse.ArgumentParser(description='Validate the minimum GCS install/startup path.')
    ap.add_argument('--rov-ip', default=base_cfg.rov_ip)
    ap.add_argument('--rov-port', type=int, default=base_cfg.rov_port)
    ap.add_argument('--bind-ip', default=base_cfg.bind_ip)
    ap.add_argument('--bind-port', type=int, default=base_cfg.bind_port)
    ap.add_argument('--skip-bind-check', action='store_true')
    args = ap.parse_args()

    cfg = TuiConfig(
        rov_ip=args.rov_ip,
        rov_port=args.rov_port,
        bind_ip=args.bind_ip,
        bind_port=args.bind_port,
        send_hz=base_cfg.send_hz,
        poll_hz=base_cfg.poll_hz,
        heartbeat_hz=base_cfg.heartbeat_hz,
        handshake_timeout_s=base_cfg.handshake_timeout_s,
        print_hz=base_cfg.print_hz,
    )
    return run_preflight(cfg, bind_check=not args.skip_bind_check)


if __name__ == '__main__':
    raise SystemExit(main())
