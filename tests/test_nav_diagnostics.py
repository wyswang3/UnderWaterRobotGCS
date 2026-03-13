from __future__ import annotations

import unittest

from urogcs.protocol.messages import (
    NAV_FLAG_DVL_BIND_MISMATCH,
    NAV_FLAG_IMU_RECONNECTING,
    StatusTelemetry,
    nav_diagnostic_summary,
)


class NavDiagnosticTests(unittest.TestCase):
    def test_summary_distinguishes_reconnect_and_mismatch(self) -> None:
        summary = nav_diagnostic_summary(
            nav_valid=0,
            nav_stale=0,
            nav_degraded=0,
            nav_fault_code=11,
            nav_status_flags=NAV_FLAG_IMU_RECONNECTING | NAV_FLAG_DVL_BIND_MISMATCH,
        )

        self.assertEqual(summary, "invalid,imu_reconnecting,dvl_mismatch")

    def test_status_properties_expose_device_bits(self) -> None:
        st = StatusTelemetry(
            nav_valid=0,
            nav_stale=0,
            nav_degraded=0,
            nav_fault_code=12,
            nav_status_flags=NAV_FLAG_IMU_RECONNECTING,
        )

        self.assertTrue(st.imu_reconnecting)
        self.assertFalse(st.imu_mismatch)
        self.assertFalse(st.imu_online)
        self.assertEqual(st.nav_fault_name, "ImuDisconnected")
        self.assertEqual(st.nav_diagnostic_summary, "invalid,imu_reconnecting")


if __name__ == "__main__":
    unittest.main()
