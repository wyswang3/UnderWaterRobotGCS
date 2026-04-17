from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from urogcs.app.gui.gui_env import GuiConfig
from urogcs.app.gui.main_window import OverviewMainWindow
from urogcs.core.service import GcsServiceState
from urogcs.protocol.messages import StatusTelemetry


class _FakeService:
    def __init__(self) -> None:
        self.connected = True
        self.state = GcsServiceState(session_established=True, link_alive=True)
        self.calls: list[tuple[bool, bool, bool]] = []

    def request_dvl_policy(self, enable: bool, *, submerged_confirmed: bool, ack_req: bool) -> None:
        self.calls.append((enable, submerged_confirmed, ack_req))

    def close(self) -> None:
        return


class GuiDvlPolicyFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _make_window(self) -> OverviewMainWindow:
        window = OverviewMainWindow(GuiConfig(), auto_connect=False)
        window._service = _FakeService()  # type: ignore[assignment]
        window._snapshot.status = StatusTelemetry(
            session_established=1,
            link_alive=1,
            dvl_policy_enabled=0,
        )
        return window

    def test_enable_dvl_requires_underwater_confirmation(self) -> None:
        window = self._make_window()
        try:
            with mock.patch(
                "urogcs.app.gui.main_window.QMessageBox.warning",
                return_value=QMessageBox.Yes,
            ) as warning:
                window._send_dvl_policy(True)

            self.assertEqual([(True, True, True)], window._service.calls)  # type: ignore[union-attr]
            warning.assert_called_once()
        finally:
            window.close()

    def test_enable_dvl_cancel_does_not_send_command(self) -> None:
        window = self._make_window()
        try:
            with mock.patch(
                "urogcs.app.gui.main_window.QMessageBox.warning",
                return_value=QMessageBox.No,
            ) as warning:
                window._send_dvl_policy(True)

            self.assertEqual([], window._service.calls)  # type: ignore[union-attr]
            warning.assert_called_once()
        finally:
            window.close()

    def test_disable_dvl_skips_confirmation_dialog(self) -> None:
        window = self._make_window()
        try:
            with mock.patch("urogcs.app.gui.main_window.QMessageBox.warning") as warning:
                window._send_dvl_policy(False)

            self.assertEqual([(False, False, True)], window._service.calls)  # type: ignore[union-attr]
            warning.assert_not_called()
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
