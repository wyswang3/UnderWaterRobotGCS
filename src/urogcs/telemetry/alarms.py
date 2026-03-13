# src/urogcs/telemetry/alarms.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from urogcs.protocol.messages import nav_diagnostic_summary
from urogcs.telemetry.model import TelemetrySnapshot


class AlarmLevel(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRIT = "crit"


class AlarmCode(str, Enum):
    SESSION_NOT_ESTABLISHED = "SESSION_NOT_ESTABLISHED"
    LINK_STALE = "LINK_STALE"
    ESTOP_ACTIVE = "ESTOP_ACTIVE"
    FAILSAFE_ACTIVE = "FAILSAFE_ACTIVE"
    NAV_UNTRUSTED = "NAV_UNTRUSTED"
    SYSTEM_FAULT = "SYSTEM_FAULT"
    COMMAND_FAILED = "COMMAND_FAILED"
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

    if bool(getattr(st, "failsafe_active", False)):
        out.append(Alarm(
            code=AlarmCode.FAILSAFE_ACTIVE,
            level=AlarmLevel.CRIT,
            title="Failsafe active",
            detail="Control core reports failsafe_active=1. Inspect nav/link/guard state.",
        ))

    if (not bool(getattr(st, "nav_valid", False))) or bool(getattr(st, "nav_stale", False)):
        diag = nav_diagnostic_summary(
            nav_valid=int(getattr(st, "nav_valid", 0)),
            nav_stale=int(getattr(st, "nav_stale", 0)),
            nav_degraded=int(getattr(st, "nav_degraded", 0)),
            nav_fault_code=int(getattr(st, "nav_fault_code", 0)),
            nav_status_flags=int(getattr(st, "nav_status_flags", 0)),
        )
        out.append(Alarm(
            code=AlarmCode.NAV_UNTRUSTED,
            level=AlarmLevel.CRIT,
            title="Navigation not trusted",
            detail=(
                "nav_valid/nav_stale indicates the current navigation snapshot must "
                f"not be treated as a trusted control input. diag={diag}."
            ),
        ))
    elif bool(getattr(st, "nav_degraded", False)):
        diag = nav_diagnostic_summary(
            nav_valid=int(getattr(st, "nav_valid", 0)),
            nav_stale=int(getattr(st, "nav_stale", 0)),
            nav_degraded=int(getattr(st, "nav_degraded", 0)),
            nav_fault_code=int(getattr(st, "nav_fault_code", 0)),
            nav_status_flags=int(getattr(st, "nav_status_flags", 0)),
        )
        out.append(Alarm(
            code=AlarmCode.NAV_UNTRUSTED,
            level=AlarmLevel.WARN,
            title="Navigation degraded",
            detail=f"nav_degraded=1 diag={diag}. Control may keep running in a limited mode only.",
        ))

    if bool(getattr(st, "fault_state", False)) or int(getattr(st, "health_state", 0)) == 3:
        out.append(Alarm(
            code=AlarmCode.SYSTEM_FAULT,
            level=AlarmLevel.CRIT,
            title="System fault active",
            detail=f"fault_state={int(getattr(st, 'fault_state', 0))} fault_code={int(getattr(st, 'last_fault_code', 0))}.",
        ))

    if int(getattr(st, "command_status", 0)) in (2, 4, 5):
        out.append(Alarm(
            code=AlarmCode.COMMAND_FAILED,
            level=AlarmLevel.WARN,
            title="Last command not applied",
            detail=(
                "Telemetry reports command_status="
                f"{int(getattr(st, 'command_status', 0))} fault_code={int(getattr(st, 'command_fault_code', 0))}."
            ),
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
