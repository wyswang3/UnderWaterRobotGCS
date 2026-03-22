from __future__ import annotations

import importlib.util
from types import SimpleNamespace
import unittest

from urogcs.telemetry.ros2_mirror_source import Ros2MirrorSnapshotSource


def _frame():
    return SimpleNamespace(
        seq=5,
        stamp_ns=12345,
        control=SimpleNamespace(
            estop_latched=0,
            armed=1,
            active_mode=2,
            failsafe_active=0,
            controller_name='heading_hold',
            desired_controller='heading_hold',
            consecutive_failures=2,
            auto_fail_limit=5,
        ),
        system=SimpleNamespace(
            session_state=3,
            nav_valid=1,
            nav_state=3,
            nav_stale=0,
            nav_degraded=1,
            fault_state=0,
            health_state=2,
            last_fault_code=0,
            nav_fault_code=0,
            nav_status_flags=(1 << 6) | (1 << 7),
        ),
        last_command_result=SimpleNamespace(status=3, fault_code=0, cmd_seq=41),
    )


def _health_monitor_msg():
    return SimpleNamespace(
        severity=2,
        summary='device_reconnecting',
        recommended_action='wait for reconnect to complete; if it does not recover, inspect USB power and cabling',
    )


class Ros2MirrorSourceTests(unittest.TestCase):
    def test_source_callback_updates_snapshot_and_service_state(self) -> None:
        source = Ros2MirrorSnapshotSource()
        source._on_telemetry(_frame())

        self.assertTrue(source.snapshot.has_status)
        assert source.snapshot.status is not None
        self.assertTrue(source.state.session_established)
        self.assertTrue(source.state.link_alive)
        self.assertEqual(source.state.active_controller, 'heading_hold')
        self.assertEqual(source.state.command_cmd_seq, 41)
        self.assertTrue(source.state.imu_online)
        self.assertTrue(source.state.dvl_online)

    def test_source_tracks_ros2_health_monitor_advisory(self) -> None:
        source = Ros2MirrorSnapshotSource()
        source._on_health_monitor(_health_monitor_msg())

        self.assertEqual(source.health_advisory.severity, 2)
        self.assertEqual(source.health_advisory.summary, 'device_reconnecting')
        self.assertIn('inspect USB power', source.health_advisory.recommended_action)

    @unittest.skipIf(importlib.util.find_spec('rclpy') is not None, 'rclpy available in this environment')
    def test_source_reports_missing_ros2_runtime_cleanly(self) -> None:
        source = Ros2MirrorSnapshotSource()
        self.assertFalse(source.start())
        self.assertIn('rclpy', source.last_error)


if __name__ == '__main__':
    unittest.main()
