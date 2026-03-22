from __future__ import annotations

import io
from contextlib import redirect_stdout
import unittest

from urogcs.app.tui import tui_view
from urogcs.app.tui.tui_view import TuiDashboard, TuiStatusSnapshot
from urogcs.protocol.wire import WireControlMode


class TuiViewTests(unittest.TestCase):
    def test_render_groups_customer_facing_statuses(self) -> None:
        dashboard = TuiDashboard()
        snapshot = TuiStatusSnapshot(
            local_estop=False,
            local_mode=WireControlMode.Auto,
            session_established=1,
            link_alive=1,
            status_age_ms=80.0,
            status_seq=21,
            remote_armed=1,
            remote_mode="Manual",
            remote_failsafe=0,
            nav_valid=0,
            nav_state="Invalid",
            nav_stale=0,
            nav_degraded=0,
            nav_fault_name="ImuDisconnected",
            nav_diag_summary="invalid,imu_reconnecting",
            imu_reconnecting=1,
            dvl_online=1,
            health_state="Fault",
            fault_state=1,
            last_fault_code=4,
            command_status="Rejected",
            command_fault_code=8,
            command_cmd_seq=22,
            last_tx_kind="SET_MODE",
            last_tx_seq=22,
            last_ack_code="OK",
        )

        buf = io.StringIO()
        original_ansi = tui_view._IS_ANSI_TERMINAL
        tui_view._IS_ANSI_TERMINAL = False
        try:
            with redirect_stdout(buf):
                dashboard.render(snapshot)
        finally:
            tui_view._IS_ANSI_TERMINAL = original_ansi

        rendered = buf.getvalue()
        self.assertIn("[CONN] state=connected", rendered)
        self.assertIn("[DEV ] overall=reconnecting imu=reconnecting dvl=online", rendered)
        self.assertIn("[NAV ] state=invalid", rendered)
        self.assertIn("transport=acknowledged", rendered)
        self.assertIn("runtime=rejected", rendered)
        self.assertIn("lifecycle=sent>acknowledged>rejected", rendered)
        self.assertIn("blocked=imu_reconnecting", rendered)
        self.assertIn("teleop_motion=single_key_only", rendered)


if __name__ == "__main__":
    unittest.main()
