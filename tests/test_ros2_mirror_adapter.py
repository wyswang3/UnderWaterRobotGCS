from __future__ import annotations

from types import SimpleNamespace
import unittest

from urogcs.protocol.wire import WireControlMode
from urogcs.telemetry.ros2_mirror_adapter import (
    build_snapshot_from_mirror,
    build_status_telemetry_from_mirror,
    infer_link_alive,
    infer_session_established,
)


def _frame(**overrides):
    frame = SimpleNamespace(
        seq=77,
        stamp_ns=123456789,
        control=SimpleNamespace(
            estop_latched=0,
            armed=1,
            active_mode=2,
            failsafe_active=0,
            controller_name='manual',
            desired_controller='manual',
            consecutive_failures=1,
            auto_fail_limit=3,
        ),
        system=SimpleNamespace(
            session_state=3,
            nav_valid=1,
            nav_state=3,
            nav_stale=0,
            nav_degraded=1,
            fault_state=0,
            health_state=2,
            last_fault_code=4,
            nav_fault_code=12,
            nav_status_flags=(1 << 10) | (1 << 9),
        ),
        last_command_result=SimpleNamespace(status=5, fault_code=13, cmd_seq=88),
    )
    for key, value in overrides.items():
        setattr(frame, key, value)
    return frame


class Ros2MirrorAdapterTests(unittest.TestCase):
    def test_adapter_reuses_gateway_status_mapping_fields(self) -> None:
        status = build_status_telemetry_from_mirror(_frame(), session_established=True, link_alive=True)

        self.assertEqual(status.session_established, 1)
        self.assertEqual(status.link_alive, 1)
        self.assertEqual(status.armed, 1)
        self.assertEqual(status.mode, int(WireControlMode.Manual))
        self.assertEqual(status.nav_fault_code, 12)
        self.assertEqual(status.nav_status_flags, (1 << 10) | (1 << 9))
        self.assertEqual(status.command_status, 5)
        self.assertEqual(status.command_fault_code, 13)
        self.assertEqual(status.active_controller, 'manual')
        self.assertEqual(status.command_cmd_seq, 88)
        self.assertEqual(status.t_ns, 123456789)

    def test_adapter_infers_connection_state_from_runtime_session_state(self) -> None:
        connected = _frame()
        disconnected = _frame(system=SimpleNamespace(
            session_state=1,
            nav_valid=0,
            nav_state=1,
            nav_stale=1,
            nav_degraded=0,
            fault_state=0,
            health_state=3,
            last_fault_code=0,
            nav_fault_code=9,
            nav_status_flags=0,
        ))

        self.assertTrue(infer_session_established(connected))
        self.assertTrue(infer_link_alive(connected))
        self.assertFalse(infer_session_established(disconnected))
        self.assertFalse(infer_link_alive(disconnected))

    def test_snapshot_builder_populates_existing_ui_snapshot(self) -> None:
        snapshot = build_snapshot_from_mirror(_frame(), now_ns=999)

        self.assertTrue(snapshot.has_status)
        self.assertEqual(snapshot.last_rx_ns, 999)
        self.assertEqual(snapshot.command_status_str, 'Failed')
        self.assertEqual(snapshot.nav_diagnostic_summary, 'degraded,imu_reconnecting,dvl_mismatch')


if __name__ == '__main__':
    unittest.main()
