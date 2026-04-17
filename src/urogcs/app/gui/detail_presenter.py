from __future__ import annotations

from typing import Any, Iterable

from urogcs.protocol.messages import (
    command_status_name,
    health_state_name,
    nav_fault_name,
    runtime_nav_state_name,
)
from urogcs.telemetry.model import TelemetrySnapshot

from .overview_presenter import OverviewCardState


def _field(value: Any, path: str, default: Any = None) -> Any:
    current = value
    marker = object()
    for part in path.split("."):
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(part, marker)
        else:
            current = getattr(current, part, marker)
        if current is marker:
            return default
    return current


def _fmt_named(values: Iterable[float], names: tuple[str, ...], *, precision: int = 2) -> str:
    parts: list[str] = []
    for name, value in zip(names, values):
        parts.append(f"{name}={float(value):+.{precision}f}")
    return "  ".join(parts)


def _fmt_channels(values: Iterable[float], *, prefix: str, precision: int = 2) -> str:
    parts: list[str] = []
    for idx, value in enumerate(values, start=1):
        parts.append(f"{prefix}{idx}={float(value):+.{precision}f}")
    return "  ".join(parts)


def _link_state_name(code: Any) -> str:
    return {
        0: "unknown",
        1: "down",
        2: "alive",
        3: "degraded",
    }.get(int(code or 0), "unknown")


def build_execution_cards(
    frame: Any,
    snapshot: TelemetrySnapshot,
) -> tuple[OverviewCardState, OverviewCardState, OverviewCardState]:
    if frame is None:
        status = snapshot.status
        summary = "Compact STATUS Only" if status is not None else "Unavailable"
        detail = (
            "Detailed requested/applied DOF, thruster command and PWM output require "
            "the ROS2 mirror `TelemetryFrameV2` source.\n"
            "Current GUI action buttons still work over the UDP command lane."
        )
        if status is not None:
            detail += (
                f"\ncommand={command_status_name(int(status.command_status))} "
                f"fault={int(status.command_fault_code)}"
            )
        unavailable = OverviewCardState(
            title="Execution Output",
            summary="ROS2 Detail Needed",
            detail=detail,
            severity="warn",
        )
        return (
            OverviewCardState("Command Lane", summary, detail, "warn"),
            unavailable,
            OverviewCardState("PWM / STM32 Link", "Awaiting Full Telemetry", detail, "warn"),
        )

    dof_names = ("surge", "sway", "heave", "roll", "pitch", "yaw")
    requested = _field(frame, "intent.dof_cmd", [0.0] * 6) or [0.0] * 6
    applied = _field(frame, "control.dof_cmd_applied", [0.0] * 6) or [0.0] * 6
    thruster = _field(frame, "control.thruster_cmd", [0.0] * 8) or [0.0] * 8
    pwm = _field(frame, "control.pwm_duty", [0.0] * 8) or [0.0] * 8

    requested_mode = _field(frame, "intent.requested_mode", 0)
    command_status = _field(frame, "last_command_result.status", 0)
    command_fault = _field(frame, "last_command_result.fault_code", 0)
    command_seq = _field(frame, "last_command_result.cmd_seq", 0)
    active_intent = _field(frame, "control.active_intent_id", 0)
    controller_name = str(_field(frame, "control.controller_name", "") or "-")
    desired_controller = str(_field(frame, "control.desired_controller", "") or "-")

    intent_card = OverviewCardState(
        title="Command Lane",
        summary=f"{command_status_name(int(command_status))} / seq={int(command_seq)}",
        detail=(
            f"requested_mode={int(requested_mode)} active_intent={int(active_intent)}\n"
            f"controller={controller_name} desired={desired_controller}\n"
            f"requested_dof:\n{_fmt_named(requested, dof_names)}\n"
            f"applied_dof:\n{_fmt_named(applied, dof_names)}\n"
            f"command_fault={int(command_fault)}"
        ),
        severity="ok" if int(command_fault) == 0 else "warn",
    )

    output_card = OverviewCardState(
        title="Thruster / PWM",
        summary="8 Channels",
        detail=(
            f"thruster_cmd:\n{_fmt_channels(thruster, prefix='T')}\n"
            f"pwm_duty:\n{_fmt_channels(pwm, prefix='P')}"
        ),
        severity="info",
    )

    stm32_link = _link_state_name(_field(frame, "system.stm32_link_state", 0))
    pwm_link = _link_state_name(_field(frame, "system.pwm_link_state", 0))
    link_card = OverviewCardState(
        title="PWM / STM32 Link",
        summary=f"STM32={stm32_link} PWM={pwm_link}",
        detail=(
            f"stm32_rtt_ms={float(_field(frame, 'system.stm32_last_rtt_ms', -1.0)):.2f}\n"
            f"pwm_tx_frames={int(_field(frame, 'system.pwm_tx_frames', 0))}\n"
            f"stm32_hb_tx={int(_field(frame, 'system.stm32_hb_tx', 0))} "
            f"ack={int(_field(frame, 'system.stm32_hb_ack', 0))}\n"
            "Per-frame STM32 execution acknowledgement is not available yet; "
            "this page shows link-level health and the latest commanded PWM."
        ),
        severity="ok" if stm32_link == "alive" and pwm_link == "alive" else "warn",
    )

    return intent_card, output_card, link_card


def build_navigation_cards(
    frame: Any,
    snapshot: TelemetrySnapshot,
) -> tuple[OverviewCardState, OverviewCardState, OverviewCardState]:
    status = snapshot.status
    if frame is None:
        nav_state = snapshot.nav_state_str
        health = snapshot.health_state_str
        fault = snapshot.nav_fault_name
        detail = (
            f"runtime_nav={nav_state}\n"
            f"health={health}\n"
            f"diag={snapshot.nav_diagnostic_summary}\n"
            f"fault={fault}\n"
            "Detailed pose/velocity vectors require ROS2 mirror `TelemetryFrameV2`."
        )
        placeholder = OverviewCardState("Motion Vectors", "ROS2 Detail Needed", detail, "warn")
        return (
            OverviewCardState("Trust Gate", nav_state, detail, "warn"),
            placeholder,
            OverviewCardState("Pose / Velocity", "Unavailable", detail, "warn"),
        )

    attitude = _field(frame, "attitude_rpy", [0.0, 0.0, 0.0]) or [0.0] * 3
    position = _field(frame, "position", [0.0, 0.0, 0.0]) or [0.0] * 3
    velocity = _field(frame, "velocity", [0.0, 0.0, 0.0]) or [0.0] * 3
    depth_m = float(_field(frame, "depth_m", 0.0) or 0.0)

    nav_state_code = int(_field(frame, "system.nav_state", 0) or 0)
    nav_health_code = int(_field(frame, "system.nav_health", 0) or 0)
    nav_valid = int(_field(frame, "system.nav_valid", 0) or 0)
    nav_stale = int(_field(frame, "system.nav_stale", 0) or 0)
    nav_degraded = int(_field(frame, "system.nav_degraded", 0) or 0)
    nav_fault_code = int(_field(frame, "system.nav_fault_code", 0) or 0)
    nav_status_flags = int(_field(frame, "system.nav_status_flags", 0) or 0)
    nav_age_ms = int(_field(frame, "system.nav_age_ms", 0) or 0)

    trust_summary = "OK"
    trust_severity = "ok"
    if nav_stale or not nav_valid:
        trust_summary = "Invalid / Stale"
        trust_severity = "crit"
    elif nav_degraded:
        trust_summary = "Degraded"
        trust_severity = "warn"

    trust_card = OverviewCardState(
        title="Trust Gate",
        summary=trust_summary,
        detail=(
            f"runtime_nav={runtime_nav_state_name(nav_state_code)}\n"
            f"health={health_state_name(nav_health_code)} age_ms={nav_age_ms}\n"
            f"valid={nav_valid} stale={nav_stale} degraded={nav_degraded}\n"
            f"fault={nav_fault_name(nav_fault_code)}({nav_fault_code})\n"
            f"status_flags=0x{nav_status_flags:04X}\n"
            f"diag={snapshot.nav_diagnostic_summary}"
        ),
        severity=trust_severity,
    )

    motion_card = OverviewCardState(
        title="Attitude / Depth",
        summary=f"depth={depth_m:.2f} m",
        detail=(
            f"rpy(rad):\n{_fmt_named(attitude, ('roll', 'pitch', 'yaw'))}\n"
            "This layer is the operator-facing motion observation surface."
        ),
        severity="info",
    )

    pose_card = OverviewCardState(
        title="Position / Velocity",
        summary="ENU Motion",
        detail=(
            f"position:\n{_fmt_named(position, ('E', 'N', 'U'))}\n"
            f"velocity:\n{_fmt_named(velocity, ('vE', 'vN', 'vU'))}"
        ),
        severity="info",
    )

    return trust_card, motion_card, pose_card


def build_power_card(frame: Any) -> OverviewCardState:
    detail_lines = [
        "Volt32 is configured on the nav side, but motor current / power are not yet mirrored into",
        "the current UI telemetry contract.",
        "",
        "Display rules for the future power page:",
        "displayed_current_a = raw_sensor_current * 40",
        "motor_bus_voltage = 24 V fixed",
        "sampled_voltage channel is divider voltage only, not the motor bus absolute voltage",
    ]

    severity = "warn"
    summary = "Awaiting Telemetry Wiring"
    if frame is not None:
        summary = "Transform Rules Ready"

    return OverviewCardState(
        title="Power / Volt32",
        summary=summary,
        detail="\n".join(detail_lines),
        severity=severity,
    )
