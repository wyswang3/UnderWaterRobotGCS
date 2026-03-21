from __future__ import annotations

import unittest

from urogcs.core.service import GcsService, GcsServiceConfig
from urogcs.protocol.messages import StatusTelemetry


class GcsServiceStateTests(unittest.TestCase):
    def test_handle_status_exposes_device_binding_flags(self) -> None:
        svc = GcsService(GcsServiceConfig())
        st = StatusTelemetry(
            nav_status_flags=(1 << 6) | (1 << 9) | (1 << 10),
        )

        svc._handle_status(st)

        self.assertTrue(svc.state.imu_online)
        self.assertTrue(svc.state.imu_reconnecting)
        self.assertTrue(svc.state.dvl_mismatch)
        self.assertFalse(svc.state.dvl_online)
        self.assertGreater(svc.state.last_status_rx_ns, 0)


if __name__ == "__main__":
    unittest.main()
