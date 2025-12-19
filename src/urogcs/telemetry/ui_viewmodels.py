# src/urogcs/telemetry/ui_viewmodels.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from urogcs.telemetry.alarms import Alarm, AlarmLevel, evaluate_alarms, AlarmPolicy
from urogcs.telemetry.model import TelemetrySnapshot


@dataclass(frozen=True)
class LinkViewModel:
    connected: bool
    age_ms: Optional[float]
    summary: str


@dataclass(frozen=True)
class StatusViewModel:
    session_established: bool
    link_alive: bool
    estop: bool
    mode: str
    active_controller: str
    desired_controller: str
    consecutive_failures: int
    auto_fail_limit: int


@dataclass(frozen=True)
class DashboardViewModel:
    link: LinkViewModel
    status: Optional[StatusViewModel]
    alarms: List[Alarm]


def _calc_age_ms(last_rx_ns: int, now_ns: int) -> Optional[float]:
    if last_rx_ns <= 0:
        return None
    return (now_ns - last_rx_ns) / 1_000_000.0


def build_dashboard_viewmodel(
    snapshot: TelemetrySnapshot,
    now_ns: int,
    alarm_policy: AlarmPolicy = AlarmPolicy(),
) -> DashboardViewModel:
    alarms = evaluate_alarms(snapshot, now_ns=now_ns, policy=alarm_policy)

    age_ms = _calc_age_ms(snapshot.last_rx_ns, now_ns)
    connected = (age_ms is not None) and (age_ms < float(alarm_policy.link_stale_ms))

    if age_ms is None:
        link_summary = "No telemetry timestamp"
    else:
        link_summary = f"STATUS age {age_ms:.0f} ms"

    link_vm = LinkViewModel(
        connected=connected,
        age_ms=age_ms,
        summary=link_summary,
    )

    if not snapshot.status:
        return DashboardViewModel(link=link_vm, status=None, alarms=alarms)

    st = snapshot.status
    status_vm = StatusViewModel(
        session_established=bool(st.session_established),
        link_alive=bool(st.link_alive),
        estop=bool(st.estop),
        mode=snapshot.mode_str,
        active_controller=str(st.active_controller),
        desired_controller=str(st.desired_controller),
        consecutive_failures=int(st.consecutive_failures),
        auto_fail_limit=int(st.auto_fail_limit),
    )

    return DashboardViewModel(link=link_vm, status=status_vm, alarms=alarms)


def highest_alarm_level(alarms: List[Alarm]) -> Optional[AlarmLevel]:
    if not alarms:
        return None
    # CRIT > WARN > INFO
    level_rank = {AlarmLevel.INFO: 1, AlarmLevel.WARN: 2, AlarmLevel.CRIT: 3}
    alarms_sorted = sorted(alarms, key=lambda a: level_rank.get(a.level, 0), reverse=True)
    return alarms_sorted[0].level
