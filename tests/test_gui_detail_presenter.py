from __future__ import annotations

from types import SimpleNamespace
import unittest

from urogcs.app.gui.detail_presenter import (
    build_execution_cards,
    build_navigation_cards,
    build_power_card,
)
from urogcs.protocol.messages import StatusTelemetry
from urogcs.telemetry.model import TelemetrySnapshot


class GuiDetailPresenterTests(unittest.TestCase):
    def test_execution_cards_use_full_mirror_frame(self) -> None:
        frame = SimpleNamespace(
            intent=SimpleNamespace(
                requested_mode=2,
                dof_cmd=[0.1, -0.2, 0.3, 0.0, 0.0, 0.4],
            ),
            control=SimpleNamespace(
                active_intent_id=77,
                controller_name="manual",
                desired_controller="manual",
                dof_cmd_applied=[0.1, -0.2, 0.25, 0.0, 0.0, 0.35],
                thruster_cmd=[0.1] * 8,
                pwm_duty=[0.52] * 8,
            ),
            system=SimpleNamespace(
                stm32_link_state=2,
                pwm_link_state=2,
                stm32_last_rtt_ms=8.5,
                pwm_tx_frames=1234,
                stm32_hb_tx=40,
                stm32_hb_ack=39,
            ),
            last_command_result=SimpleNamespace(
                status=3,
                fault_code=0,
                cmd_seq=91,
            ),
        )
        snapshot = TelemetrySnapshot(
            status=StatusTelemetry(command_status=3, command_fault_code=0),
            last_rx_ns=100,
        )

        intent_card, output_card, link_card = build_execution_cards(frame, snapshot)

        self.assertEqual(intent_card.summary, "Executed / seq=91")
        self.assertIn("requested_dof", intent_card.detail)
        self.assertIn("thruster_cmd", output_card.detail)
        self.assertIn("pwm_duty", output_card.detail)
        self.assertEqual(link_card.summary, "STM32=alive PWM=alive")
        self.assertIn("Per-frame STM32 execution acknowledgement is not available yet", link_card.detail)

    def test_navigation_cards_report_runtime_trust(self) -> None:
        frame = SimpleNamespace(
            attitude_rpy=[0.1, 0.2, 0.3],
            position=[1.0, 2.0, -3.0],
            velocity=[0.5, 0.0, -0.1],
            depth_m=3.2,
            system=SimpleNamespace(
                nav_state=3,
                nav_health=1,
                nav_valid=1,
                nav_stale=0,
                nav_degraded=1,
                nav_fault_code=0,
                nav_status_flags=0x0043,
                nav_age_ms=120,
            ),
        )
        snapshot = TelemetrySnapshot(
            status=StatusTelemetry(
                nav_valid=1,
                nav_state=3,
                nav_stale=0,
                nav_degraded=1,
                nav_fault_code=0,
                nav_status_flags=0x0043,
            ),
            last_rx_ns=100,
        )

        trust_card, motion_card, pose_card = build_navigation_cards(frame, snapshot)

        self.assertEqual(trust_card.summary, "Degraded")
        self.assertIn("status_flags=0x0043", trust_card.detail)
        self.assertIn("depth=3.20 m", motion_card.summary)
        self.assertIn("position", pose_card.detail)
        self.assertIn("velocity", pose_card.detail)

    def test_power_card_explains_volt32_transform_rules(self) -> None:
        card = build_power_card(frame=None)
        self.assertEqual(card.summary, "Awaiting Telemetry Wiring")
        self.assertIn("displayed_current_a = raw_sensor_current * 40", card.detail)
        self.assertIn("motor_bus_voltage = 24 V fixed", card.detail)


if __name__ == "__main__":
    unittest.main()
