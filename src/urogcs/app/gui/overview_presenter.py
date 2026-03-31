from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from urogcs.core.service import GcsServiceState
from urogcs.protocol.wire import AckCode
from urogcs.telemetry.alarms import AlarmLevel
from urogcs.telemetry.model import TelemetrySnapshot
from urogcs.telemetry.ui_viewmodels import (
    DashboardViewModel,
    build_dashboard_viewmodel,
    highest_alarm_level,
)


@dataclass(frozen=True)
class OverviewCardState:
    title: str
    summary: str
    detail: str
    severity: str = "neutral"


@dataclass(frozen=True)
class OverviewDashboardState:
    header_title: str
    header_detail: str
    connection: OverviewCardState
    device: OverviewCardState
    navigation: OverviewCardState
    control: OverviewCardState
    command: OverviewCardState
    faults: OverviewCardState
    footer: str


@dataclass(frozen=True)
class OverviewContext:
    rov_addr: str
    bind_addr: str
    last_log: str = ""
    telemetry_source: str = "udp"
    advisory_summary: str = ""
    advisory_recommended_action: str = ""
    advisory_severity: int = 0


def build_overview_state(
    snapshot: TelemetrySnapshot,
    service_state: GcsServiceState,
    *,
    now_ns: int,
    context: OverviewContext,
) -> OverviewDashboardState:
    vm = build_dashboard_viewmodel(snapshot, now_ns=now_ns)
    return OverviewDashboardState(
        header_title="Overview Dashboard",
        header_detail=(
            f"target={context.rov_addr}    bind={context.bind_addr}    "
            f"source={_source_text(context)}    session={_session_text(service_state)}"
        ),
        connection=_build_connection_card(vm, service_state),
        device=_build_device_card(vm),
        navigation=_build_navigation_card(vm),
        control=_build_control_card(vm),
        command=_build_command_card(vm, service_state),
        faults=_build_fault_card(
            vm,
            context.last_log,
            context.advisory_summary,
            context.advisory_recommended_action,
            context.advisory_severity,
        ),
        footer=_build_footer(context),
    )


def _session_text(service_state: GcsServiceState) -> str:
    if service_state.session_id is None:
        return "none"
    return str(service_state.session_id)


def _source_text(context: OverviewContext) -> str:
    if context.telemetry_source == "ros2":
        return "ros2_preview"
    return context.telemetry_source or "udp"


def _advisory_severity(level: int) -> str:
    if level >= 3:
        return "crit"
    if level == 2:
        return "warn"
    if level == 1:
        return "ok"
    return "neutral"


def _build_footer(context: OverviewContext) -> str:
    if context.last_log:
        return context.last_log
    if context.advisory_recommended_action and context.advisory_summary not in {"", "ok"}:
        return f"advisory={context.advisory_summary}; action={context.advisory_recommended_action}"
    return (
        "Primary lane: supervisor + GCS TUI teleop. GUI is read-only status/motion observer. "
        "Keyboard motion remains TUI-only and one key at a time."
    )


def _build_connection_card(
    vm: DashboardViewModel,
    service_state: GcsServiceState,
) -> OverviewCardState:
    age_ms = vm.link.age_ms
    if vm.status is None:
        if service_state.session_established:
            return OverviewCardState(
                title="Connection",
                summary="Connected, waiting status",
                detail="Handshake completed but no STATUS frame has been decoded yet.",
                severity="warn",
            )
        return OverviewCardState(
            title="Connection",
            summary="Disconnected",
            detail="No telemetry snapshot yet. Check gcs_server, UDP bind, and target IP/port.",
            severity="crit",
        )

    if vm.link.connected and vm.status.session_established and vm.status.link_alive:
        summary = "Connected"
        severity = "ok"
    elif vm.status.session_established and not vm.status.link_alive:
        summary = "Telemetry stale"
        severity = "warn"
    elif vm.status.session_established:
        summary = "Waiting status"
        severity = "warn"
    else:
        summary = "Handshake incomplete"
        severity = "crit"

    age_text = "n/a" if age_ms is None else f"{age_ms:.0f} ms"
    detail = (
        f"{vm.link.summary}\n"
        f"link_alive={int(vm.status.link_alive)} session_established={int(vm.status.session_established)}\n"
        f"last_status_age={age_text}"
    )
    return OverviewCardState("Connection", summary, detail, severity)


def _device_state(online: bool, reconnecting: bool, mismatch: bool) -> str:
    if mismatch:
        return "mismatch"
    if reconnecting:
        return "reconnecting"
    if online:
        return "online"
    return "device_offline"


def _build_device_card(vm: DashboardViewModel) -> OverviewCardState:
    if vm.status is None:
        return OverviewCardState(
            title="Devices",
            summary="Unknown",
            detail="No STATUS frame yet, so IMU/DVL device state is unknown.",
            severity="warn",
        )

    st = vm.status
    imu_state = st.imu_state
    dvl_state = st.dvl_state

    if "format_invalid" in {imu_state, dvl_state}:
        overall = "Format Invalid"
        severity = "crit"
    elif "stale" in {imu_state, dvl_state}:
        overall = "Stale / Reconnecting"
        severity = "warn"
    elif st.capability_level == "relative_nav":
        overall = "IMU + DVL"
        severity = "ok"
    elif st.capability_level == "attitude_feedback":
        overall = "IMU Only"
        severity = "info"
    else:
        overall = "Control Only"
        severity = "info"

    detail = (
        f"IMU={imu_state} note={st.imu_state_detail}\n"
        f"DVL={dvl_state} note={st.dvl_state_detail}\n"
        f"Volt32=not present in STATUS; use supervisor/device-scan/preflight for not_present/open_failed/permission diagnostics\n"
        f"observation_level={st.capability_level}"
    )
    return OverviewCardState("Devices", overall, detail, severity)


def _build_navigation_card(vm: DashboardViewModel) -> OverviewCardState:
    if vm.status is None:
        return OverviewCardState(
            title="Motion Info",
            summary="Unknown",
            detail="No runtime status is available yet, so capability and motion observation remain unknown.",
            severity="warn",
        )

    st = vm.status
    capability_titles = {
        "control_only": "Control Only",
        "attitude_feedback": "Attitude Feedback",
        "relative_nav": "Relative Nav",
        "full_stack_preview": "Full Stack Preview",
    }
    capability_fields = {
        "control_only": "minimal runtime state only",
        "attitude_feedback": "roll/pitch/yaw, gyro, accel",
        "relative_nav": "roll/pitch/yaw, gyro, accel, velocity, relative_position",
        "full_stack_preview": "reserved",
    }
    summary = capability_titles.get(st.capability_level, "Control Only")
    if st.capability_level == "relative_nav":
        severity = "ok" if st.nav_valid and not st.nav_stale and not st.nav_degraded else "warn"
    else:
        severity = "info"

    detail = (
        f"observation_level={st.capability_level}\n"
        f"note={st.capability_summary}\n"
        f"usable={capability_fields.get(st.capability_level, 'minimal runtime state only')}\n"
        f"observe={st.motion_observation_hint}\n"
        f"sensor_diag=imu:{st.imu_state},dvl:{st.dvl_state}\n"
        f"runtime_nav={st.nav_state} health={st.health_state}\n"
        f"diag={st.nav_diagnostic_summary}\n"
        f"fault={st.nav_fault_name}({st.nav_fault_code})"
    )
    return OverviewCardState("Motion Info", summary, detail, severity)


def _build_control_card(vm: DashboardViewModel) -> OverviewCardState:
    if vm.status is None:
        return OverviewCardState(
            title="Control",
            summary="Unknown",
            detail="No runtime control state is available yet.",
            severity="warn",
        )

    st = vm.status
    if st.estop:
        summary = "E-Stop latched"
        severity = "crit"
    elif st.failsafe_active:
        summary = "Failsafe"
        severity = "crit"
    elif st.armed:
        summary = f"Armed / {st.mode}"
        severity = "ok"
    else:
        summary = f"Disarmed / {st.mode}"
        severity = "warn"

    controller_name = st.active_controller or "-"
    desired_name = st.desired_controller or "-"
    detail = (
        f"controller={controller_name}\n"
        f"desired={desired_name}\n"
        f"fault_state={int(st.fault_state)} fails={st.consecutive_failures}/{st.auto_fail_limit}"
    )
    return OverviewCardState("Control", summary, detail, severity)


def _transport_state(service_state: GcsServiceState) -> str:
    if service_state.waiting_ack:
        return "pending_ack"
    if service_state.last_tx_seq is None:
        return "idle"
    if service_state.last_ack_seq == service_state.last_tx_seq:
        if service_state.last_ack_code is None:
            return "acknowledged"
        try:
            ack_name = AckCode(int(service_state.last_ack_code)).name
        except Exception:
            ack_name = str(service_state.last_ack_code)
        if ack_name == "OK":
            return "acknowledged"
        return f"ack_{ack_name.lower()}"
    return "sent"


def _runtime_state(vm: DashboardViewModel) -> str:
    if vm.status is None:
        return "none"
    return (vm.status.command_status or "None").lower()


def _command_severity(transport: str, runtime: str) -> str:
    if runtime in {"rejected", "expired", "failed"} or transport.startswith("ack_"):
        return "crit"
    if runtime in {"accepted", "executed"} or transport == "acknowledged":
        return "ok"
    if transport in {"pending_ack", "sent"}:
        return "warn"
    return "neutral"


def _build_command_card(vm: DashboardViewModel, service_state: GcsServiceState) -> OverviewCardState:
    transport = _transport_state(service_state)
    runtime = _runtime_state(vm)
    severity = _command_severity(transport, runtime)

    if service_state.last_tx_seq is None and runtime == "none":
        summary = "Idle"
    else:
        summary = f"{transport} / {runtime}"

    tx_kind = service_state.last_tx_kind or "-"
    tx_seq = "-" if service_state.last_tx_seq is None else str(service_state.last_tx_seq)
    cmd_seq = "-"
    fault_code = "0"
    if vm.status is not None:
        cmd_seq = str(vm.status.command_cmd_seq)
        fault_code = str(vm.status.command_fault_code)

    detail = (
        f"last_tx={tx_kind}#{tx_seq}\n"
        f"transport={transport}\n"
        f"runtime={runtime} cmd_seq={cmd_seq} fault={fault_code}"
    )
    return OverviewCardState("Command", summary, detail, severity)


def _alarm_level_to_severity(level: Optional[AlarmLevel]) -> str:
    if level == AlarmLevel.CRIT:
        return "crit"
    if level == AlarmLevel.WARN:
        return "warn"
    if level == AlarmLevel.INFO:
        return "info"
    return "ok"


def _build_fault_card(
    vm: DashboardViewModel,
    last_log: str,
    advisory_summary: str,
    advisory_recommended_action: str,
    advisory_severity: int,
) -> OverviewCardState:
    advisory_summary = advisory_summary.strip()
    advisory_recommended_action = advisory_recommended_action.strip()

    if not vm.alarms:
        if advisory_summary and advisory_summary != "ok":
            lines = [f"ros2_advisory={advisory_summary}"]
            if advisory_recommended_action:
                lines.append(f"action={advisory_recommended_action}")
            if last_log:
                lines.append(f"last_log={last_log}")
            return OverviewCardState(
                "Fault Summary",
                f"ADVISORY / {advisory_summary}",
                "\n".join(lines),
                _advisory_severity(advisory_severity),
            )

        detail = "No active alarms."
        if last_log:
            detail += f"\nlast_log={last_log}"
        return OverviewCardState("Fault Summary", "No active alarm", detail, "ok")

    highest = highest_alarm_level(vm.alarms)
    summary = f"{highest.value.upper()} / {vm.alarms[0].title}" if highest else vm.alarms[0].title

    lines = []
    for alarm in vm.alarms[:3]:
        detail = alarm.detail.strip()
        if detail:
            lines.append(f"{alarm.level.value.upper()} {alarm.title}: {detail}")
        else:
            lines.append(f"{alarm.level.value.upper()} {alarm.title}")
    if advisory_summary and advisory_summary != "ok":
        lines.append(f"ros2_advisory={advisory_summary}")
        if advisory_recommended_action:
            lines.append(f"action={advisory_recommended_action}")
    if last_log:
        lines.append(f"last_log={last_log}")

    return OverviewCardState(
        "Fault Summary",
        summary,
        "\n".join(lines),
        _alarm_level_to_severity(highest),
    )
