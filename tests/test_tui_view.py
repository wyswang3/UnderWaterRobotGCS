from __future__ import annotations

import io
from contextlib import redirect_stdout
import unittest

from urogcs.app.tui import tui_view
from urogcs.app.tui.tui_view import TuiDashboard, TuiStatusSnapshot
from urogcs.protocol.wire import WireControlMode


class TuiViewTests(unittest.TestCase):
    def test_render_includes_replay_nav_diag_and_command_result(self) -> None:
        dashboard = TuiDashboard()
        snapshot = TuiStatusSnapshot(
            local_estop=False,
            local_mode=WireControlMode.Manual,
            remote_armed=1,
            remote_mode="Failsafe",
            remote_failsafe=1,
            nav_valid=0,
            nav_state="Invalid",
            nav_stale=1,
            nav_degraded=1,
            nav_fault_name="DvlDeviceMismatch",
            nav_diag_summary="invalid,dvl_mismatch",
            health_state="Fault",
            fault_state=1,
            last_fault_code=4,
            command_status="Rejected",
            command_cmd_seq=22,
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
        self.assertIn("diag=invalid,dvl_mismatch", rendered)
        self.assertIn("runtime=Rejected cmd_seq=22", rendered)


if __name__ == "__main__":
    unittest.main()
