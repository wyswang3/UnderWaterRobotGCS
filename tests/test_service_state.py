from __future__ import annotations

from types import SimpleNamespace
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

    def test_request_dvl_policy_forwards_enable_and_submerged_confirmation(self) -> None:
        svc = GcsService(GcsServiceConfig())

        class FakeClient:
            def __init__(self) -> None:
                self.state = SimpleNamespace(session_id=9, established=True)
                self.last_tx_seq = 12
                self.last_tx_kind = "DVL_POLICY"
                self.last_tx_time_ns = 345
                self.waiting_ack = True
                self.pending_ack_seq = 12
                self.pending_ack_kind = "DVL_POLICY"
                self.last_ack_seq = None
                self.last_ack_kind = ""
                self.last_ack_code = None
                self.last_ack_reason = None
                self.calls: list[tuple[bool, bool, bool]] = []

            def send_dvl_policy(self, enable: bool, *, submerged_confirmed: bool, ack_req: bool) -> None:
                self.calls.append((enable, submerged_confirmed, ack_req))

        fake = FakeClient()
        svc._cli = fake  # type: ignore[assignment]

        svc.request_dvl_policy(True, submerged_confirmed=True, ack_req=True)

        self.assertEqual([(True, True, True)], fake.calls)
        self.assertEqual("DVL_POLICY", svc.state.last_tx_kind)
        self.assertTrue(svc.state.waiting_ack)
        self.assertEqual(12, svc.state.pending_ack_seq)


if __name__ == "__main__":
    unittest.main()
