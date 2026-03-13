from __future__ import annotations

import unittest

from urogcs.protocol.messages import StatusTelemetry
from urogcs.telemetry.alarms import AlarmCode, evaluate_alarms
from urogcs.telemetry.model import TelemetrySnapshot
from urogcs.telemetry.ui_viewmodels import build_dashboard_viewmodel


class TelemetryViewModelTests(unittest.TestCase):
    def test_dashboard_viewmodel_uses_runtime_status_fields(self) -> None:
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
                nav_status_flags=(1 << 6) | (1 << 7),
                fault_state=0,
                health_state=2,
                command_status=3,
                last_fault_code=4,
                command_fault_code=0,
                active_controller="heading_hold",
                desired_controller="heading_hold",
                consecutive_failures=1,
                auto_fail_limit=5,
                status_seq=99,
                command_cmd_seq=123,
                t_ns=456,
            ),
            last_rx_ns=2_000_000_000,
        )

        vm = build_dashboard_viewmodel(snapshot, now_ns=2_100_000_000)

        self.assertIsNotNone(vm.status)
        assert vm.status is not None
        self.assertTrue(vm.status.armed)
        self.assertEqual(vm.status.mode, "Manual")
        self.assertEqual(vm.status.nav_state, "Ok")
        self.assertEqual(vm.status.nav_fault_name, "None")
        self.assertEqual(vm.status.nav_diagnostic_summary, "degraded")
        self.assertTrue(vm.status.imu_online)
        self.assertTrue(vm.status.dvl_online)
        self.assertEqual(vm.status.health_state, "Degraded")
        self.assertEqual(vm.status.command_status, "Executed")
        self.assertEqual(vm.status.status_seq, 99)
        self.assertEqual(vm.status.command_cmd_seq, 123)

    def test_alarms_flag_failsafe_nav_fault_and_command_failure(self) -> None:
        snapshot = TelemetrySnapshot(
            status=StatusTelemetry(
                session_established=1,
                link_alive=1,
                armed=0,
                estop=0,
                mode=3,
                failsafe_active=1,
                nav_valid=0,
                nav_state=1,
                nav_stale=1,
                nav_degraded=0,
                nav_fault_code=12,
                nav_status_flags=(1 << 10),
                fault_state=1,
                health_state=3,
                command_status=5,
                last_fault_code=6,
                command_fault_code=12,
            ),
            last_rx_ns=1_000_000_000,
        )

        alarms = evaluate_alarms(snapshot, now_ns=1_050_000_000)
        codes = {alarm.code for alarm in alarms}

        self.assertIn(AlarmCode.FAILSAFE_ACTIVE, codes)
        self.assertIn(AlarmCode.NAV_UNTRUSTED, codes)
        self.assertIn(AlarmCode.SYSTEM_FAULT, codes)
        self.assertIn(AlarmCode.COMMAND_FAILED, codes)
        nav_alarm = next(alarm for alarm in alarms if alarm.code == AlarmCode.NAV_UNTRUSTED)
        self.assertIn("imu_reconnecting", nav_alarm.detail)


if __name__ == "__main__":
    unittest.main()
