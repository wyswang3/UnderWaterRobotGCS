from __future__ import annotations

"""Read-only adapter from ROS2 mirror telemetry into the existing GCS model.

This module intentionally reuses the legacy `StatusTelemetry` compression logic
that `gcs_server` already applies in C++. The GUI/TUI can therefore consume
ROS2 mirror data without inventing a second UI-specific status contract.
"""

import time
from typing import Any, Optional

from urogcs.protocol.messages import StatusTelemetry
from urogcs.protocol.wire import WireControlMode
from urogcs.telemetry.model import TelemetrySnapshot

RUNTIME_MODE_NONE = 1
RUNTIME_MODE_MANUAL = 2
RUNTIME_MODE_AUTO = 3
RUNTIME_MODE_FAILSAFE = 4

SESSION_CONNECTED = 2
SESSION_READY = 3


def _field(value: Any, path: str, default: Any = 0) -> Any:
    current = value
    marker = object()
    for part in path.split('.'):
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(part, marker)
        else:
            current = getattr(current, part, marker)
        if current is marker:
            return default
    return current


def _to_wire_mode(runtime_mode: int) -> int:
    runtime_mode = int(runtime_mode)
    if runtime_mode == RUNTIME_MODE_MANUAL:
        return int(WireControlMode.Manual)
    if runtime_mode == RUNTIME_MODE_AUTO:
        return int(WireControlMode.Auto)
    if runtime_mode == RUNTIME_MODE_FAILSAFE:
        return int(WireControlMode.Failsafe)
    if runtime_mode == RUNTIME_MODE_NONE:
        return int(WireControlMode.Unknown)
    return int(WireControlMode.Unknown)


def infer_session_established(frame: Any) -> bool:
    """Infer session-ready state from the mirrored runtime session enum.

    This is a fallback for the ROS2 preview path only. The authority transport
    session booleans still belong to the gateway when the UDP path is used.
    """
    return int(_field(frame, 'system.session_state', 0)) >= SESSION_READY


def infer_link_alive(frame: Any) -> bool:
    return int(_field(frame, 'system.session_state', 0)) >= SESSION_CONNECTED


def build_status_telemetry_from_mirror(
    frame: Any,
    *,
    session_established: Optional[bool] = None,
    link_alive: Optional[bool] = None,
) -> StatusTelemetry:
    """Mirror `TelemetryFrameV2` into the existing compact UI telemetry model."""
    session_established = infer_session_established(frame) if session_established is None else bool(session_established)
    link_alive = infer_link_alive(frame) if link_alive is None else bool(link_alive)

    return StatusTelemetry(
        session_established=1 if session_established else 0,
        link_alive=1 if link_alive else 0,
        estop=int(_field(frame, 'control.estop_latched', 0)),
        armed=int(_field(frame, 'control.armed', 0)),
        mode=_to_wire_mode(int(_field(frame, 'control.active_mode', 0))),
        failsafe_active=int(_field(frame, 'control.failsafe_active', 0)),
        nav_valid=int(_field(frame, 'system.nav_valid', 0)),
        nav_state=int(_field(frame, 'system.nav_state', 0)),
        nav_stale=int(_field(frame, 'system.nav_stale', 0)),
        nav_degraded=int(_field(frame, 'system.nav_degraded', 0)),
        fault_state=int(_field(frame, 'system.fault_state', 0)),
        health_state=int(_field(frame, 'system.health_state', 0)),
        command_status=int(_field(frame, 'last_command_result.status', 0)),
        last_fault_code=int(_field(frame, 'system.last_fault_code', 0)),
        command_fault_code=int(_field(frame, 'last_command_result.fault_code', 0)),
        nav_fault_code=int(_field(frame, 'system.nav_fault_code', 0)),
        nav_status_flags=int(_field(frame, 'system.nav_status_flags', 0)),
        active_controller=str(_field(frame, 'control.controller_name', '')),
        desired_controller=str(_field(frame, 'control.desired_controller', '')),
        consecutive_failures=int(_field(frame, 'control.consecutive_failures', 0)),
        auto_fail_limit=int(_field(frame, 'control.auto_fail_limit', 0)),
        status_seq=int(_field(frame, 'seq', 0)) & 0xFFFFFFFF,
        command_cmd_seq=int(_field(frame, 'last_command_result.cmd_seq', 0)),
        t_ns=int(_field(frame, 'stamp_ns', 0)),
    )


def build_snapshot_from_mirror(
    frame: Any,
    *,
    now_ns: Optional[int] = None,
    session_established: Optional[bool] = None,
    link_alive: Optional[bool] = None,
) -> TelemetrySnapshot:
    status = build_status_telemetry_from_mirror(
        frame,
        session_established=session_established,
        link_alive=link_alive,
    )
    return TelemetrySnapshot(status=status, last_rx_ns=int(now_ns if now_ns is not None else time.monotonic_ns()))
