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
    armed: bool
    estop: bool
    mode: str
    failsafe_active: bool
    nav_valid: bool
    nav_state: str
    nav_stale: bool
    nav_degraded: bool
    nav_fault_code: int
    nav_fault_name: str
    nav_status_flags: int
    nav_diagnostic_summary: str
    imu_online: bool
    dvl_online: bool
    imu_reconnecting: bool
    dvl_reconnecting: bool
    imu_mismatch: bool
    dvl_mismatch: bool
    health_state: str
    fault_state: bool
    command_status: str
    last_fault_code: int
    command_fault_code: int
    active_controller: str
    desired_controller: str
    consecutive_failures: int
    auto_fail_limit: int
    status_seq: int
    command_cmd_seq: int
    t_ns: int


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
        armed=bool(st.armed),
        estop=bool(st.estop),
        mode=snapshot.mode_str,
        failsafe_active=bool(st.failsafe_active),
        nav_valid=bool(st.nav_valid),
        nav_state=snapshot.nav_state_str,
        nav_stale=bool(st.nav_stale),
        nav_degraded=bool(st.nav_degraded),
        nav_fault_code=int(st.nav_fault_code),
        nav_fault_name=st.nav_fault_name,
        nav_status_flags=int(st.nav_status_flags),
        nav_diagnostic_summary=st.nav_diagnostic_summary,
        imu_online=st.imu_online,
        dvl_online=st.dvl_online,
        imu_reconnecting=st.imu_reconnecting,
        dvl_reconnecting=st.dvl_reconnecting,
        imu_mismatch=st.imu_mismatch,
        dvl_mismatch=st.dvl_mismatch,
        health_state=snapshot.health_state_str,
        fault_state=bool(st.fault_state),
        command_status=snapshot.command_status_str,
        last_fault_code=int(st.last_fault_code),
        command_fault_code=int(st.command_fault_code),
        active_controller=str(st.active_controller),
        desired_controller=str(st.desired_controller),
        consecutive_failures=int(st.consecutive_failures),
        auto_fail_limit=int(st.auto_fail_limit),
        status_seq=int(st.status_seq),
        command_cmd_seq=int(st.command_cmd_seq),
        t_ns=int(st.t_ns),
    )

    return DashboardViewModel(link=link_vm, status=status_vm, alarms=alarms)


def highest_alarm_level(alarms: List[Alarm]) -> Optional[AlarmLevel]:
    if not alarms:
        return None
    # CRIT > WARN > INFO
    level_rank = {AlarmLevel.INFO: 1, AlarmLevel.WARN: 2, AlarmLevel.CRIT: 3}
    alarms_sorted = sorted(alarms, key=lambda a: level_rank.get(a.level, 0), reverse=True)
    return alarms_sorted[0].level
