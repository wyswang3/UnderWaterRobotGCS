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
            f"session={_session_text(service_state)}"
        ),
        connection=_build_connection_card(vm, service_state),
        device=_build_device_card(vm),
        navigation=_build_navigation_card(vm),
        control=_build_control_card(vm),
        command=_build_command_card(vm, service_state),
        faults=_build_fault_card(vm, context.last_log),
        footer=context.last_log or "GUI ready. Waiting for telemetry updates.",
    )


def _session_text(service_state: GcsServiceState) -> str:
    if service_state.session_id is None:
        return "none"
    return str(service_state.session_id)


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
    imu_state = _device_state(st.imu_online, st.imu_reconnecting, st.imu_mismatch)
    dvl_state = _device_state(st.dvl_online, st.dvl_reconnecting, st.dvl_mismatch)

    if "mismatch" in {imu_state, dvl_state}:
        overall = "Mismatch"
        severity = "crit"
    elif "reconnecting" in {imu_state, dvl_state}:
        overall = "Reconnecting"
        severity = "warn"
    elif imu_state == "online" and dvl_state == "online":
        overall = "Online"
        severity = "ok"
    elif imu_state == "device_offline" and dvl_state == "device_offline":
        overall = "Offline"
        severity = "crit"
    else:
        overall = "Degraded"
        severity = "warn"

    detail = f"IMU={imu_state}\nDVL={dvl_state}"
    return OverviewCardState("Devices", overall, detail, severity)


def _build_navigation_card(vm: DashboardViewModel) -> OverviewCardState:
    if vm.status is None:
        return OverviewCardState(
            title="Navigation",
            summary="Unknown",
            detail="No navigation telemetry decoded yet.",
            severity="warn",
        )

    st = vm.status
    if not st.nav_valid:
        summary = "Invalid"
        severity = "crit"
    elif st.nav_stale:
        summary = "Stale"
        severity = "crit"
    elif st.nav_degraded:
        summary = "Degraded"
        severity = "warn"
    else:
        summary = "Ok"
        severity = "ok"

    detail = (
        f"state={st.nav_state} health={st.health_state}\n"
        f"diag={st.nav_diagnostic_summary}\n"
        f"fault={st.nav_fault_name}({st.nav_fault_code})"
    )
    return OverviewCardState("Navigation", summary, detail, severity)


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


def _build_fault_card(vm: DashboardViewModel, last_log: str) -> OverviewCardState:
    if not vm.alarms:
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
    if last_log:
        lines.append(f"last_log={last_log}")

    return OverviewCardState(
        "Fault Summary",
        summary,
        "\n".join(lines),
        _alarm_level_to_severity(highest),
    )
