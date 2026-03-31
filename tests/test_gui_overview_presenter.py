from __future__ import annotations

import unittest

from urogcs.app.gui.overview_presenter import OverviewContext, build_overview_state
from urogcs.core.service import GcsServiceState
from urogcs.protocol.messages import StatusTelemetry
from urogcs.telemetry.model import TelemetrySnapshot


class GuiOverviewPresenterTests(unittest.TestCase):
    def test_presenter_combines_connection_device_nav_control_and_command_states(self) -> None:
        snapshot = TelemetrySnapshot(
            status=StatusTelemetry(
                session_established=1,
                link_alive=1,
                armed=1,
                estop=0,
                mode=1,
                failsafe_active=0,
                nav_valid=1,
                nav_state=3,
                nav_stale=0,
                nav_degraded=1,
                nav_fault_code=0,
                nav_status_flags=(1 << 6) | (1 << 11),
                fault_state=0,
                health_state=2,
                command_status=3,
                last_fault_code=0,
                command_fault_code=0,
                active_controller="heading_hold",
                desired_controller="heading_hold",
                consecutive_failures=1,
                auto_fail_limit=5,
                status_seq=42,
                command_cmd_seq=19,
            ),
            last_rx_ns=2_000_000_000,
        )
        service_state = GcsServiceState(
            session_established=True,
            session_id=123,
            link_alive=True,
            last_tx_seq=19,
            last_tx_kind="ARM",
            last_ack_seq=19,
            last_ack_kind="ARM",
            last_ack_code=0,
        )

        state = build_overview_state(
            snapshot,
            service_state,
            now_ns=2_100_000_000,
            context=OverviewContext(
                rov_addr="127.0.0.1:14550",
                bind_addr="0.0.0.0:14551",
                last_log="[HS] session established",
            ),
        )

        self.assertEqual(state.connection.summary, "Connected")
        self.assertEqual(state.device.summary, "Stale / Reconnecting")
        self.assertEqual(state.navigation.title, "Motion Info")
        self.assertEqual(state.navigation.summary, "Attitude Feedback")
        self.assertEqual(state.control.summary, "Armed / Manual")
        self.assertEqual(state.command.summary, "acknowledged / executed")
        self.assertEqual(state.command.severity, "ok")
        self.assertIn("heading_hold", state.control.detail)
        self.assertIn("IMU 在线时可观察姿态反馈", state.navigation.detail)
        self.assertIn("sensor_diag=imu:online,dvl:stale", state.navigation.detail)
        self.assertIn("DVL=stale", state.device.detail)
        self.assertIn("observation_level=attitude_feedback", state.navigation.detail)
        self.assertIn("last_log=[HS] session established", state.faults.detail)

    def test_presenter_reports_relative_nav_when_imu_and_dvl_are_online(self) -> None:
        snapshot = TelemetrySnapshot(
            status=StatusTelemetry(
                session_established=1,
                link_alive=1,
                armed=0,
                estop=0,
                mode=1,
                failsafe_active=0,
                nav_valid=1,
                nav_state=3,
                nav_stale=0,
                nav_degraded=0,
                nav_fault_code=0,
                nav_status_flags=(1 << 6) | (1 << 7),
                fault_state=0,
                health_state=1,
                command_status=0,
                last_fault_code=0,
                command_fault_code=0,
                active_controller="manual",
                desired_controller="manual",
                consecutive_failures=0,
                auto_fail_limit=5,
                status_seq=44,
                command_cmd_seq=0,
            ),
            last_rx_ns=3_000_000_000,
        )

        state = build_overview_state(
            snapshot,
            GcsServiceState(session_established=True, session_id=8, link_alive=True),
            now_ns=3_010_000_000,
            context=OverviewContext(
                rov_addr="127.0.0.1:14550",
                bind_addr="0.0.0.0:14551",
            ),
        )

        self.assertEqual(state.device.summary, "IMU + DVL")
        self.assertEqual(state.navigation.summary, "Relative Nav")
        self.assertIn("这不代表绝对定位", state.navigation.detail)

    def test_presenter_surfaces_ros2_advisory_recovery_text(self) -> None:
        snapshot = TelemetrySnapshot(
            status=StatusTelemetry(
                session_established=1,
                link_alive=1,
                armed=0,
                estop=0,
                mode=1,
                failsafe_active=0,
                nav_valid=1,
                nav_state=3,
                nav_stale=0,
                nav_degraded=0,
                nav_fault_code=0,
                nav_status_flags=(1 << 6) | (1 << 7),
                fault_state=0,
                health_state=1,
                command_status=0,
                last_fault_code=0,
                command_fault_code=0,
                active_controller="manual",
                desired_controller="manual",
                consecutive_failures=0,
                auto_fail_limit=5,
                status_seq=43,
                command_cmd_seq=0,
            ),
            last_rx_ns=3_000_000_000,
        )

        state = build_overview_state(
            snapshot,
            GcsServiceState(session_established=True, session_id=7, link_alive=True),
            now_ns=3_050_000_000,
            context=OverviewContext(
                rov_addr="127.0.0.1:14550",
                bind_addr="0.0.0.0:14551",
                telemetry_source="ros2",
                advisory_summary="device_reconnecting",
                advisory_recommended_action="wait for reconnect to complete; if it does not recover, inspect USB power and cabling",
                advisory_severity=2,
            ),
        )

        self.assertIn("source=ros2_preview", state.header_detail)
        self.assertEqual(state.faults.summary, "ADVISORY / device_reconnecting")
        self.assertEqual(state.faults.severity, "warn")
        self.assertIn("action=wait for reconnect to complete", state.faults.detail)
        self.assertIn("advisory=device_reconnecting", state.footer)

    def test_presenter_reports_disconnected_without_status(self) -> None:
        state = build_overview_state(
            TelemetrySnapshot(),
            GcsServiceState(),
            now_ns=100,
            context=OverviewContext(
                rov_addr="127.0.0.1:14550",
                bind_addr="0.0.0.0:14551",
            ),
        )

        self.assertEqual(state.connection.summary, "Disconnected")
        self.assertEqual(state.command.summary, "Idle")
        self.assertEqual(state.faults.severity, "warn")
        self.assertIn("TUI teleop", state.footer)
        self.assertIn("one key at a time", state.footer)


if __name__ == "__main__":
    unittest.main()
