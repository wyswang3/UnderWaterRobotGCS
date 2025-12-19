# src/urogcs/telemetry/alarms.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from urogcs.telemetry.model import TelemetrySnapshot


class AlarmLevel(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRIT = "crit"


class AlarmCode(str, Enum):
    SESSION_NOT_ESTABLISHED = "SESSION_NOT_ESTABLISHED"
    LINK_STALE = "LINK_STALE"
    ESTOP_ACTIVE = "ESTOP_ACTIVE"
    FAIL_COUNTER_GROWING = "FAIL_COUNTER_GROWING"


@dataclass(frozen=True)
class Alarm:
    code: AlarmCode
    level: AlarmLevel
    title: str
    detail: str = ""


@dataclass(frozen=True)
class AlarmPolicy:
    """
    Conservative defaults for pool/bench testing.
    - link_stale_ms: if no STATUS received within this time, raise LINK_STALE
    - fail_warn_threshold: consecutive_failures >= this -> WARN
    - fail_crit_threshold: consecutive_failures >= this -> CRIT
    """
    link_stale_ms: int = 600  # ~0.6s (telem_hz=10 => 100ms expected)
    fail_warn_threshold: int = 3
    fail_crit_threshold: int = 10


def evaluate_alarms(snapshot: TelemetrySnapshot, now_ns: int, policy: AlarmPolicy = AlarmPolicy()) -> List[Alarm]:
    """
    Convert telemetry snapshot into a list of alarms.
    UI layer can sort/filter by level.

    Inputs:
      - snapshot: latest telemetry snapshot (may have no status yet)
      - now_ns: monotonic_ns() from caller
    """
    out: List[Alarm] = []

    if not snapshot.status:
        out.append(Alarm(
            code=AlarmCode.SESSION_NOT_ESTABLISHED,
            level=AlarmLevel.WARN,
            title="No telemetry yet",
            detail="No STATUS received. Check UDP bind/port and vehicle comm_gcs.",
        ))
        return out

    st = snapshot.status

    # 1) Link stale (based on last RX timestamp kept by snapshot)
    if snapshot.last_rx_ns > 0:
        age_ms = (now_ns - snapshot.last_rx_ns) / 1_000_000.0
        if age_ms >= float(policy.link_stale_ms):
            out.append(Alarm(
                code=AlarmCode.LINK_STALE,
                level=AlarmLevel.CRIT,
                title="Telemetry link stale",
                detail=f"Last STATUS age={age_ms:.0f} ms (threshold={policy.link_stale_ms} ms).",
            ))
    else:
        out.append(Alarm(
            code=AlarmCode.LINK_STALE,
            level=AlarmLevel.WARN,
            title="Telemetry timestamp missing",
            detail="Snapshot.last_rx_ns is 0; cannot evaluate link age.",
        ))

    # 2) Session established?
    if not bool(st.session_established):
        out.append(Alarm(
            code=AlarmCode.SESSION_NOT_ESTABLISHED,
            level=AlarmLevel.WARN,
            title="Session not established",
            detail="Handshake may not be completed (CONNECT_REQ/ACK/CONFIRM).",
        ))

    # 3) E-stop
    if bool(st.estop):
        out.append(Alarm(
            code=AlarmCode.ESTOP_ACTIVE,
            level=AlarmLevel.CRIT,
            title="E-Stop active",
            detail="Vehicle reports ESTOP=1. Clear estop to resume thrusters.",
        ))

    # 4) Failure counters (from your wire telemetry)
    cf = int(st.consecutive_failures)
    if cf >= policy.fail_crit_threshold:
        out.append(Alarm(
            code=AlarmCode.FAIL_COUNTER_GROWING,
            level=AlarmLevel.CRIT,
            title="Failures accumulating",
            detail=f"consecutive_failures={cf} (crit>={policy.fail_crit_threshold}).",
        ))
    elif cf >= policy.fail_warn_threshold:
        out.append(Alarm(
            code=AlarmCode.FAIL_COUNTER_GROWING,
            level=AlarmLevel.WARN,
            title="Failures accumulating",
            detail=f"consecutive_failures={cf} (warn>={policy.fail_warn_threshold}).",
        ))

    return out
