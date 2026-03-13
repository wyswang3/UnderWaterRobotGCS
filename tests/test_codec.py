from __future__ import annotations

import struct
import unittest

from urogcs.protocol.codec import decode_status


def _cstr16(text: str) -> bytes:
    raw = text.encode("utf-8")
    raw = raw[:15]
    return raw + b"\x00" + (b"\x00" * (15 - len(raw)))


class StatusCodecTests(unittest.TestCase):
    def test_decode_status_v1_exposes_authoritative_runtime_fields(self) -> None:
        payload = struct.pack(
            "<14B H H H H I I I Q 16s 16s Q",
            1, 1, 0, 1,
            2, 1, 1, 3,
            0, 1, 1, 2,
            3, 0,
            4,
            12, 8, 0x0440,
            5, 9, 77,
            123456789,
            _cstr16("depth_hold"),
            _cstr16("depth_hold"),
            987654321,
        )

        st = decode_status(payload)

        self.assertEqual(st.session_established, 1)
        self.assertEqual(st.armed, 1)
        self.assertEqual(st.mode, 2)
        self.assertEqual(st.failsafe_active, 1)
        self.assertEqual(st.nav_valid, 1)
        self.assertEqual(st.nav_state, 3)
        self.assertEqual(st.nav_degraded, 1)
        self.assertEqual(st.fault_state, 1)
        self.assertEqual(st.health_state, 2)
        self.assertEqual(st.command_status, 3)
        self.assertEqual(st.last_fault_code, 4)
        self.assertEqual(st.command_fault_code, 12)
        self.assertEqual(st.nav_fault_code, 8)
        self.assertEqual(st.nav_status_flags, 0x0440)
        self.assertEqual(st.status_seq, 77)
        self.assertEqual(st.command_cmd_seq, 123456789)
        self.assertEqual(st.active_controller, "depth_hold")
        self.assertEqual(st.t_ns, 987654321)

    def test_decode_status_legacy_payload_is_backward_compatible(self) -> None:
        payload = struct.pack(
            "<4B 2B H 16s 16s I I Q",
            1, 1, 1, 0,
            1, 0, 0,
            _cstr16("manual"),
            _cstr16("manual"),
            2, 10,
            42,
        )

        st = decode_status(payload)

        self.assertEqual(st.session_established, 1)
        self.assertEqual(st.link_alive, 1)
        self.assertEqual(st.estop, 1)
        self.assertEqual(st.mode, 1)
        self.assertEqual(st.active_controller, "manual")
        self.assertEqual(st.desired_controller, "manual")
        self.assertEqual(st.consecutive_failures, 2)
        self.assertEqual(st.auto_fail_limit, 10)
        self.assertEqual(st.t_ns, 42)
        self.assertEqual(st.command_status, 0)
        self.assertEqual(st.status_seq, 0)


if __name__ == "__main__":
    unittest.main()
