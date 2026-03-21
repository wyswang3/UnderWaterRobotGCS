from __future__ import annotations

"""Optional GUI/TUI data source backed by ROS2 mirror topics.

This source is read-only and intended only for outer-plane preview paths. It
consumes `/rov/telemetry` mirror data and updates the existing GCS snapshot
model. It does not send control, heartbeat, or safety decisions over ROS2.
"""

import time
from typing import Callable, Optional

from urogcs.core.service import GcsServiceState
from urogcs.telemetry.model import TelemetrySnapshot
from urogcs.telemetry.ros2_mirror_adapter import build_snapshot_from_mirror

LogCallback = Callable[[str], None]


class Ros2MirrorSnapshotSource:
    def __init__(self, *, telemetry_topic: str = '/rov/telemetry', on_log: Optional[LogCallback] = None) -> None:
        self.telemetry_topic = telemetry_topic
        self._user_on_log = on_log
        self._snapshot = TelemetrySnapshot()
        self._state = GcsServiceState()
        self._rclpy = None
        self._node = None
        self._initialised_here = False
        self._telemetry_cls = None
        self.last_error = ''

    @property
    def snapshot(self) -> TelemetrySnapshot:
        return self._snapshot

    @property
    def state(self) -> GcsServiceState:
        return self._state

    def start(self) -> bool:
        try:
            import rclpy
            from rclpy.node import Node
            from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
            from rov_msgs.msg import TelemetryFrameV2
        except ModuleNotFoundError as exc:
            self.last_error = 'ROS2 mirror source requires rclpy and generated rov_msgs Python modules'
            self._log(self.last_error)
            return False

        self._rclpy = rclpy
        self._telemetry_cls = TelemetryFrameV2
        if not rclpy.ok():
            rclpy.init(args=None)
            self._initialised_here = True

        self._node = Node('urogcs_ros2_mirror_source')
        qos = QoSProfile(depth=5)
        qos.reliability = ReliabilityPolicy.BEST_EFFORT
        qos.history = HistoryPolicy.KEEP_LAST
        qos.durability = DurabilityPolicy.VOLATILE
        self._node.create_subscription(TelemetryFrameV2, self.telemetry_topic, self._on_telemetry, qos)
        self.last_error = ''
        self._log(f'ROS2 mirror source subscribed: {self.telemetry_topic}')
        return True

    def poll(self, max_callbacks: int = 16) -> None:
        if self._node is None or self._rclpy is None:
            return
        for _ in range(max_callbacks):
            self._rclpy.spin_once(self._node, timeout_sec=0.0)

    def close(self) -> None:
        if self._node is not None:
            self._node.destroy_node()
            self._node = None
        if self._rclpy is not None and self._initialised_here:
            self._rclpy.shutdown()
        self._rclpy = None
        self._initialised_here = False

    def _on_telemetry(self, msg: object) -> None:
        snapshot = build_snapshot_from_mirror(msg, now_ns=time.monotonic_ns())
        self._snapshot = snapshot
        status = snapshot.status
        if status is None:
            return

        self._state.session_established = bool(status.session_established)
        self._state.link_alive = bool(status.link_alive)
        self._state.armed = bool(status.armed)
        self._state.estop = bool(status.estop)
        self._state.mode = int(status.mode)
        self._state.failsafe_active = bool(status.failsafe_active)
        self._state.nav_valid = bool(status.nav_valid)
        self._state.nav_state = int(status.nav_state)
        self._state.nav_stale = bool(status.nav_stale)
        self._state.nav_degraded = bool(status.nav_degraded)
        self._state.nav_fault_code = int(status.nav_fault_code)
        self._state.nav_status_flags = int(status.nav_status_flags)
        self._state.imu_online = bool(status.imu_online)
        self._state.dvl_online = bool(status.dvl_online)
        self._state.imu_reconnecting = bool(status.imu_reconnecting)
        self._state.dvl_reconnecting = bool(status.dvl_reconnecting)
        self._state.imu_mismatch = bool(status.imu_mismatch)
        self._state.dvl_mismatch = bool(status.dvl_mismatch)
        self._state.fault_state = bool(status.fault_state)
        self._state.health_state = int(status.health_state)
        self._state.command_status = int(status.command_status)
        self._state.last_fault_code = int(status.last_fault_code)
        self._state.command_fault_code = int(status.command_fault_code)
        self._state.status_seq = int(status.status_seq)
        self._state.command_cmd_seq = int(status.command_cmd_seq)
        self._state.t_ns = int(status.t_ns)
        self._state.last_status_rx_ns = int(snapshot.last_rx_ns)
        self._state.active_controller = str(status.active_controller)
        self._state.desired_controller = str(status.desired_controller)
        self._state.consecutive_failures = int(status.consecutive_failures)
        self._state.auto_fail_limit = int(status.auto_fail_limit)
        self._state.last_status_raw = status

    def _log(self, msg: str) -> None:
        if self._user_on_log is not None:
            self._user_on_log(msg)
