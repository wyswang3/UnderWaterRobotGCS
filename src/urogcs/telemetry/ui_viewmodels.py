# src/urogcs/telemetry/ui_viewmodels.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from urogcs.telemetry.alarms import Alarm, AlarmLevel, evaluate_alarms, AlarmPolicy
from urogcs.telemetry.model import TelemetrySnapshot


def derive_capability_level(*, imu_online: bool, dvl_online: bool) -> str:
    if imu_online and dvl_online:
        return 'relative_nav'
    if imu_online:
        return 'attitude_feedback'
    return 'control_only'


def capability_level_summary(level: str) -> str:
    return {
        'control_only': '当前没有可直接依赖的运动反馈；系统仍可遥控、状态观察、日志记录和 bundle 导出。',
        'attitude_feedback': 'IMU 在线时可观察姿态反馈；这不代表系统已进入完整导航。',
        'relative_nav': 'IMU + DVL 在线时可观察相对运动；这不代表绝对定位。',
        'full_stack_preview': '仅保留预留预览口径，当前不进入默认 operator lane。',
    }.get(level, '当前没有可直接依赖的运动反馈；系统仍可遥控、状态观察、日志记录和 bundle 导出。')


def motion_observation_hint(level: str) -> str:
    return {
        'control_only': '当前 lane 仍按 teleop primary 的最小状态显示；无姿态/速度数值不应被解释为系统故障。',
        'attitude_feedback': '可观察姿态角、角速度和加速度；不要把 IMU-only 写成完整导航。',
        'relative_nav': '可结合速度和短时相对运动观察；当前表达是观测能力，不代表完整导航已启用。',
        'full_stack_preview': '预留能力，当前不作为默认显示口径。',
    }.get(level, '当前只显示最小状态。')


def derive_sensor_observation_state(
    sensor: str,
    *,
    online: bool,
    reconnecting: bool,
    mismatch: bool,
    nav_stale: bool,
    nav_fault_code: int,
    capability_level: str,
) -> tuple[str, str]:
    label = 'IMU' if sensor == 'imu' else 'DVL'
    if mismatch:
        return 'format_invalid', f'{label} bind/status mismatch detected; confirm by-id binding and raw samples.'
    if reconnecting:
        return 'stale', f'{label} reconnecting; wait for fresh low-rate status before judging the sensor.'
    if online and nav_stale:
        return 'stale', f'{label} reports online, but current navigation/motion output is stale.'
    if online:
        return 'online', f'{label} online.'

    if sensor == 'dvl':
        if capability_level in {'control_only', 'attitude_feedback'}:
            return 'optional_missing', 'DVL is an external optional module; teleop primary lane can continue without it.'
        return 'not_present', 'relative_nav needs DVL, but no online DVL is currently reported.'

    if nav_fault_code == 11:
        return 'format_invalid', 'IMU mismatch is reported by nav status; verify binding and sample format.'
    if capability_level == 'control_only':
        return 'not_present', 'No online IMU is reported; teleop primary remains in control_only.'
    return 'not_present', 'IMU-backed attitude feedback is not currently available.'


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
    capability_level: str
    capability_summary: str
    motion_observation_hint: str
    imu_online: bool
    dvl_online: bool
    imu_reconnecting: bool
    dvl_reconnecting: bool
    imu_mismatch: bool
    dvl_mismatch: bool
    imu_state: str
    imu_state_detail: str
    dvl_state: str
    dvl_state_detail: str
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
    capability_level = derive_capability_level(
        imu_online=st.imu_online,
        dvl_online=st.dvl_online,
    )
    imu_state, imu_state_detail = derive_sensor_observation_state(
        'imu',
        online=st.imu_online,
        reconnecting=st.imu_reconnecting,
        mismatch=st.imu_mismatch,
        nav_stale=bool(st.nav_stale),
        nav_fault_code=int(st.nav_fault_code),
        capability_level=capability_level,
    )
    dvl_state, dvl_state_detail = derive_sensor_observation_state(
        'dvl',
        online=st.dvl_online,
        reconnecting=st.dvl_reconnecting,
        mismatch=st.dvl_mismatch,
        nav_stale=bool(st.nav_stale),
        nav_fault_code=int(st.nav_fault_code),
        capability_level=capability_level,
    )

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
        capability_level=capability_level,
        capability_summary=capability_level_summary(capability_level),
        motion_observation_hint=motion_observation_hint(capability_level),
        imu_online=st.imu_online,
        dvl_online=st.dvl_online,
        imu_reconnecting=st.imu_reconnecting,
        dvl_reconnecting=st.dvl_reconnecting,
        imu_mismatch=st.imu_mismatch,
        dvl_mismatch=st.dvl_mismatch,
        imu_state=imu_state,
        imu_state_detail=imu_state_detail,
        dvl_state=dvl_state,
        dvl_state_detail=dvl_state_detail,
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
