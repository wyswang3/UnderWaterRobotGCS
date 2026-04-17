"""Qt main window for the GCS overview dashboard.

作用：
- 组织 GUI 页面、定时刷新和操作按钮；
- 连接 GcsService 与 presenter，把运行态快照转换成可视化卡片和操作反馈。

实现思路：
- 窗口层负责控件生命周期、定时器和用户交互；
- 状态解释和文案计算尽量交给 presenter/viewmodel 模块，避免 UI 代码里混入大量业务判断。
"""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QFormLayout,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from urogcs.core.service import GcsService, GcsServiceConfig, GcsServiceState
from urogcs.protocol.messages import DofCommand
from urogcs.protocol.wire import WireControlMode
from urogcs.telemetry.model import TelemetrySnapshot
from urogcs.telemetry.ros2_mirror_source import Ros2MirrorSnapshotSource

from .detail_presenter import (
    build_execution_cards,
    build_navigation_cards,
    build_power_card,
)
from .gui_env import GuiConfig
from .overview_presenter import OverviewCardState, OverviewContext, build_overview_state


class StatusCard(QFrame):
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusCard")
        self._title = QLabel(title)
        self._title.setObjectName("CardTitle")
        self._summary = QLabel("-")
        self._summary.setObjectName("CardSummary")
        self._detail = QLabel("-")
        self._detail.setObjectName("CardDetail")
        self._detail.setWordWrap(True)
        self._detail.setTextFormat(Qt.PlainText)
        self._detail.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._detail.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        layout.addWidget(self._title)
        layout.addWidget(self._summary)
        layout.addWidget(self._detail, 1)

        self.set_state(OverviewCardState(title=title, summary="-", detail="-", severity="neutral"))

    def set_state(self, state: OverviewCardState) -> None:
        self._title.setText(state.title)
        self._summary.setText(state.summary)
        self._detail.setText(state.detail)

        color_map = {
            "ok": "#126e3a",
            "info": "#1769aa",
            "warn": "#9a6700",
            "crit": "#b42318",
            "neutral": "#334155",
        }
        border_map = {
            "ok": "#8fd19e",
            "info": "#90caf9",
            "warn": "#f3c969",
            "crit": "#f1a29b",
            "neutral": "#d7dee5",
        }
        summary_color = color_map.get(state.severity, color_map["neutral"])
        border_color = border_map.get(state.severity, border_map["neutral"])
        self._summary.setStyleSheet(f"color: {summary_color};")
        self.setStyleSheet(
            "QFrame#StatusCard {"
            f"border: 1px solid {border_color};"
            "border-radius: 12px;"
            "background: #ffffff;"
            "}"
        )


class OverviewMainWindow(QMainWindow):
    def __init__(self, cfg: GuiConfig, *, auto_connect: bool = True) -> None:
        super().__init__()
        self._cfg = cfg
        self._service: Optional[GcsService] = None
        self._ros2_source: Optional[Ros2MirrorSnapshotSource] = None
        self._snapshot = TelemetrySnapshot()
        self._last_log = ""

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_service)
        self._hb_timer = QTimer(self)
        self._hb_timer.timeout.connect(self._send_heartbeat)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_dashboard)

        self._target_label = QLabel()
        self._target_label.setObjectName("HeaderDetail")
        self._status_label = QLabel("Disconnected")
        self._status_label.setObjectName("HeaderStatus")
        self._status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._connect_button = QPushButton("Connect")
        self._connect_button.clicked.connect(self.connect_service)
        self._disconnect_button = QPushButton("Disconnect")
        self._disconnect_button.clicked.connect(self.disconnect_service)
        self._disconnect_button.setEnabled(False)

        self._connection_card = StatusCard("Connection")
        self._device_card = StatusCard("Devices")
        self._navigation_card = StatusCard("Motion Info")
        self._control_card = StatusCard("Control")
        self._command_card = StatusCard("Command")
        self._fault_card = StatusCard("Fault Summary")
        self._operate_lane_card = StatusCard("Operator Lane")
        self._operate_command_card = StatusCard("Last Command")
        self._execution_intent_card = StatusCard("Command Lane")
        self._execution_output_card = StatusCard("Thruster / PWM")
        self._execution_link_card = StatusCard("PWM / STM32 Link")
        self._nav_trust_card = StatusCard("Trust Gate")
        self._nav_motion_card = StatusCard("Attitude / Depth")
        self._nav_pose_card = StatusCard("Position / Velocity")
        self._power_card = StatusCard("Power / Volt32")
        self._footer_label = QLabel("GUI ready. Waiting for telemetry updates.")
        self._footer_label.setObjectName("FooterLabel")
        self._footer_label.setWordWrap(True)
        self._footer_label.setTextFormat(Qt.PlainText)
        self._tabs = QTabWidget()

        self._manual_mode_button = QPushButton("Manual")
        self._auto_mode_button = QPushButton("Auto")
        self._failsafe_mode_button = QPushButton("Failsafe")
        self._arm_button = QPushButton("Arm")
        self._disarm_button = QPushButton("Disarm")
        self._estop_button = QPushButton("ESTOP")
        self._clear_estop_button = QPushButton("Clear ESTOP")
        self._apply_dof_button = QPushButton("Apply DOF")
        self._zero_dof_button = QPushButton("Zero DOF")
        self._live_send_check = QCheckBox("Live Send")
        self._dvl_enable_button = QPushButton("Enable DVL")
        self._dvl_disable_button = QPushButton("Disable DVL")
        self._dof_spins: dict[str, QDoubleSpinBox] = {}

        self.setWindowTitle(cfg.window_title)
        self.resize(1180, 760)
        self._build_ui()
        self._wire_actions()
        self._apply_style()
        self._refresh_dashboard()

        if auto_connect:
            QTimer.singleShot(0, self.connect_service)

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)

        title = QLabel(self._cfg.window_title)
        title.setObjectName("HeaderTitle")

        header_left = QVBoxLayout()
        header_left.setSpacing(2)
        header_left.addWidget(title)
        header_left.addWidget(self._target_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addWidget(self._connect_button)
        button_row.addWidget(self._disconnect_button)
        button_row.addStretch(1)
        button_row.addWidget(self._status_label)

        header = QHBoxLayout()
        header.setSpacing(20)
        header.addLayout(header_left, 1)
        header.addLayout(button_row, 1)

        self._tabs.addTab(self._build_overview_tab(), "Overview")
        self._tabs.addTab(self._build_operate_tab(), "Operate")
        self._tabs.addTab(self._build_execution_tab(), "Execution")
        self._tabs.addTab(self._build_navigation_tab(), "Navigation")
        self._tabs.addTab(self._build_power_tab(), "Power")

        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)
        layout.addLayout(header)
        layout.addWidget(self._tabs, 1)
        layout.addWidget(self._footer_label)

    def _build_overview_tab(self) -> QWidget:
        page = QWidget(self)
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.addWidget(self._connection_card, 0, 0)
        grid.addWidget(self._device_card, 0, 1)
        grid.addWidget(self._navigation_card, 0, 2)
        grid.addWidget(self._control_card, 1, 0)
        grid.addWidget(self._command_card, 1, 1)
        grid.addWidget(self._fault_card, 1, 2)
        return page

    def _build_operate_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        action_column = QVBoxLayout()
        action_column.setSpacing(14)

        safety_box = QGroupBox("Safety / Mode")
        safety_layout = QVBoxLayout(safety_box)
        safety_layout.setSpacing(10)

        safety_row = QHBoxLayout()
        safety_row.setSpacing(8)
        safety_row.addWidget(self._estop_button)
        safety_row.addWidget(self._clear_estop_button)
        safety_row.addWidget(self._arm_button)
        safety_row.addWidget(self._disarm_button)
        safety_layout.addLayout(safety_row)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_row.addWidget(self._manual_mode_button)
        mode_row.addWidget(self._auto_mode_button)
        mode_row.addWidget(self._failsafe_mode_button)
        safety_layout.addLayout(mode_row)

        dof_box = QGroupBox("DOF Command")
        dof_layout = QVBoxLayout(dof_box)
        dof_layout.setSpacing(10)
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        for axis in ("surge", "sway", "heave", "roll", "pitch", "yaw"):
            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            spin.setRange(-1.0, 1.0)
            spin.setSingleStep(0.05)
            spin.setValue(0.0)
            spin.valueChanged.connect(self._maybe_live_send_dof)
            self._dof_spins[axis] = spin
            form.addRow(axis.capitalize(), spin)
        dof_layout.addLayout(form)

        dof_action_row = QHBoxLayout()
        dof_action_row.setSpacing(8)
        dof_action_row.addWidget(self._apply_dof_button)
        dof_action_row.addWidget(self._zero_dof_button)
        dof_action_row.addWidget(self._live_send_check)
        dof_action_row.addStretch(1)
        dof_layout.addLayout(dof_action_row)

        action_column.addWidget(safety_box)
        dvl_box = QGroupBox("DVL Policy")
        dvl_layout = QVBoxLayout(dvl_box)
        dvl_layout.setSpacing(10)

        dvl_note = QLabel(
            "Enable DVL only after the operator confirms the transducer is already submerged. "
            "Applying this policy restarts the navigation preview lane."
        )
        dvl_note.setWordWrap(True)
        dvl_note.setObjectName("CardDetail")
        dvl_layout.addWidget(dvl_note)

        dvl_row = QHBoxLayout()
        dvl_row.setSpacing(8)
        dvl_row.addWidget(self._dvl_enable_button)
        dvl_row.addWidget(self._dvl_disable_button)
        dvl_row.addStretch(1)
        dvl_layout.addLayout(dvl_row)

        action_column.addWidget(dvl_box)
        action_column.addWidget(dof_box)
        action_column.addStretch(1)

        state_column = QVBoxLayout()
        state_column.setSpacing(14)
        state_column.addWidget(self._operate_lane_card)
        state_column.addWidget(self._operate_command_card)
        state_column.addStretch(1)

        layout.addLayout(action_column, 5)
        layout.addLayout(state_column, 4)
        return page

    def _build_execution_tab(self) -> QWidget:
        page = QWidget(self)
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.addWidget(self._execution_intent_card, 0, 0)
        grid.addWidget(self._execution_output_card, 0, 1)
        grid.addWidget(self._execution_link_card, 1, 0, 1, 2)
        return page

    def _build_navigation_tab(self) -> QWidget:
        page = QWidget(self)
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.addWidget(self._nav_trust_card, 0, 0)
        grid.addWidget(self._nav_motion_card, 0, 1)
        grid.addWidget(self._nav_pose_card, 1, 0, 1, 2)
        return page

    def _build_power_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._power_card)
        layout.addStretch(1)
        return page

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #f3f5f7;
                color: #1f2937;
                font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
            }
            QLabel#HeaderTitle {
                font-size: 28px;
                font-weight: 700;
                color: #102a43;
            }
            QLabel#HeaderDetail {
                font-size: 13px;
                color: #52606d;
            }
            QLabel#HeaderStatus {
                font-size: 13px;
                font-weight: 600;
                color: #334155;
                padding: 8px 12px;
                background: #ffffff;
                border: 1px solid #d7dee5;
                border-radius: 10px;
            }
            QLabel#CardTitle {
                font-size: 12px;
                font-weight: 700;
                color: #52606d;
                text-transform: uppercase;
            }
            QLabel#CardSummary {
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#CardDetail {
                font-size: 13px;
                color: #334155;
            }
            QLabel#FooterLabel {
                font-size: 12px;
                color: #52606d;
                padding: 12px 14px;
                background: #ffffff;
                border: 1px solid #d7dee5;
                border-radius: 10px;
            }
            QTabWidget::pane {
                border: 1px solid #d7dee5;
                border-radius: 14px;
                background: #f8fafc;
                top: -1px;
            }
            QTabBar::tab {
                background: #e8edf2;
                color: #334155;
                padding: 10px 18px;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                margin-right: 6px;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #102a43;
            }
            QGroupBox {
                border: 1px solid #d7dee5;
                border-radius: 12px;
                margin-top: 12px;
                padding: 16px 14px 14px 14px;
                background: #ffffff;
                font-weight: 700;
                color: #334155;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px;
            }
            QPushButton {
                min-width: 110px;
                padding: 9px 14px;
                border-radius: 9px;
                border: 1px solid #c4ccd4;
                background: #ffffff;
                color: #102a43;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #eef2f6;
            }
            QPushButton:disabled {
                color: #94a3b8;
                background: #f8fafc;
            }
            QDoubleSpinBox {
                min-height: 34px;
                padding: 4px 8px;
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
            }
            QCheckBox {
                color: #334155;
                font-weight: 600;
            }
            """
        )

    def _wire_actions(self) -> None:
        self._estop_button.clicked.connect(lambda: self._send_estop(True))
        self._clear_estop_button.clicked.connect(lambda: self._send_estop(False))
        self._arm_button.clicked.connect(lambda: self._send_arm(True))
        self._disarm_button.clicked.connect(lambda: self._send_arm(False))
        self._manual_mode_button.clicked.connect(
            lambda: self._send_mode(WireControlMode.Manual)
        )
        self._auto_mode_button.clicked.connect(lambda: self._send_mode(WireControlMode.Auto))
        self._failsafe_mode_button.clicked.connect(
            lambda: self._send_mode(WireControlMode.Failsafe)
        )
        self._dvl_enable_button.clicked.connect(lambda: self._send_dvl_policy(True))
        self._dvl_disable_button.clicked.connect(lambda: self._send_dvl_policy(False))
        self._apply_dof_button.clicked.connect(self._send_current_dof)
        self._zero_dof_button.clicked.connect(self._zero_dof)

    def _control_ready(self) -> bool:
        return self._service is not None and self._service.connected

    def _send_estop(self, latched: bool) -> None:
        if not self._control_ready():
            self._on_log("[GUI] command lane not ready; connect UDP control first")
            self._refresh_dashboard()
            return
        self._service.request_estop(latched, ack_req=True)
        self._on_log(f"[GUI] estop request -> {int(latched)}")
        self._refresh_dashboard()

    def _send_arm(self, armed: bool) -> None:
        if not self._control_ready():
            self._on_log("[GUI] command lane not ready; connect UDP control first")
            self._refresh_dashboard()
            return
        self._service.request_arm(armed, ack_req=True)
        self._on_log(f"[GUI] arm request -> {int(armed)}")
        self._refresh_dashboard()

    def _send_mode(self, mode: WireControlMode) -> None:
        if not self._control_ready():
            self._on_log("[GUI] command lane not ready; connect UDP control first")
            self._refresh_dashboard()
            return
        self._service.request_mode(mode, auto_controller="", ack_req=True)
        self._on_log(f"[GUI] mode request -> {mode.name}")
        self._refresh_dashboard()

    def _build_local_dof_command(self) -> DofCommand:
        return DofCommand(
            surge=float(self._dof_spins["surge"].value()),
            sway=float(self._dof_spins["sway"].value()),
            heave=float(self._dof_spins["heave"].value()),
            roll=float(self._dof_spins["roll"].value()),
            pitch=float(self._dof_spins["pitch"].value()),
            yaw=float(self._dof_spins["yaw"].value()),
        )

    def _remote_dvl_policy_enabled(self) -> bool | None:
        status = self._snapshot.status
        if status is None:
            return None
        return bool(getattr(status, "dvl_policy_enabled", 0))

    def _send_current_dof(self) -> None:
        if not self._control_ready():
            self._on_log("[GUI] command lane not ready; connect UDP control first")
            self._refresh_dashboard()
            return
        cmd = self._build_local_dof_command()
        self._service.send_dof(cmd, ack_req=False)
        self._on_log(
            "[GUI] dof request -> "
            f"s={cmd.surge:+.2f} sw={cmd.sway:+.2f} h={cmd.heave:+.2f} "
            f"r={cmd.roll:+.2f} p={cmd.pitch:+.2f} y={cmd.yaw:+.2f}"
        )
        self._refresh_dashboard()

    def _zero_dof(self) -> None:
        for spin in self._dof_spins.values():
            spin.blockSignals(True)
            spin.setValue(0.0)
            spin.blockSignals(False)
        self._on_log("[GUI] local DOF intent reset to zero")
        if self._live_send_check.isChecked():
            self._send_current_dof()
        else:
            self._refresh_dashboard()

    def _maybe_live_send_dof(self) -> None:
        if self._live_send_check.isChecked():
            self._send_current_dof()

    def _send_dvl_policy(self, enable: bool) -> None:
        if not self._control_ready():
            self._on_log("[GUI] command lane not ready; connect UDP control first")
            self._refresh_dashboard()
            return

        submerged_confirmed = False
        if enable:
            answer = QMessageBox.warning(
                self,
                "Confirm DVL Start",
                (
                    "DVL should only be enabled after the operator confirms the transducer is already in water.\n\n"
                    "Applying this policy will restart the navigation preview lane.\n\n"
                    "Confirm the DVL is already submerged and continue?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self._on_log("[GUI] DVL enable cancelled by operator")
                self._refresh_dashboard()
                return
            submerged_confirmed = True

        self._service.request_dvl_policy(
            enable,
            submerged_confirmed=submerged_confirmed,
            ack_req=True,
        )
        self._on_log(
            "[GUI] dvl policy request -> "
            f"{'enabled' if enable else 'disabled'}"
        )
        self._refresh_dashboard()

    def _make_service(self) -> GcsService:
        svc_cfg = GcsServiceConfig(
            rov_ip=self._cfg.rov_ip,
            rov_port=self._cfg.rov_port,
            bind_ip=self._cfg.bind_ip,
            bind_port=self._cfg.bind_port,
            poll_hz=self._cfg.poll_hz,
            heartbeat_hz=self._cfg.heartbeat_hz,
            handshake_timeout_s=self._cfg.handshake_timeout_s,
            session_debug=self._cfg.session_debug,
        )
        return GcsService(svc_cfg, on_status=self._on_status, on_log=self._on_log)

    def connect_service(self) -> None:
        if self._service is not None or self._ros2_source is not None:
            return

        self._last_log = "Connecting to vehicle..."
        self._status_label.setText("Connecting...")
        QApplication.processEvents()

        service = self._make_service()
        ok = service.start()
        if ok:
            cli = service.client
            if cli is not None:
                try:
                    self._cfg.bind_ip, self._cfg.bind_port = cli.bind_addr
                except Exception:
                    pass
            self._service = service
        else:
            self._last_log = service.last_error or "Handshake failed."
            service.close()
            self._service = None

        if self._cfg.telemetry_source == "ros2":
            source = Ros2MirrorSnapshotSource(on_log=self._on_log)
            ros2_ok = source.start()
            if ros2_ok:
                self._ros2_source = source
            else:
                source.close()
                self._ros2_source = None
                if self._service is None:
                    self._last_log = source.last_error or "ROS2 mirror source failed."
                else:
                    self._last_log = (
                        self._last_log + " | " + (source.last_error or "ROS2 mirror source failed.")
                    )

        if self._service is None and self._ros2_source is None:
            self._snapshot = TelemetrySnapshot()
            self._stop_timers()
            self._connect_button.setEnabled(True)
            self._disconnect_button.setEnabled(False)
            self._refresh_dashboard()
            return

        self._connect_button.setEnabled(False)
        self._disconnect_button.setEnabled(True)
        self._start_timers()
        self._refresh_dashboard()

    def disconnect_service(self) -> None:
        if self._service is not None:
            try:
                self._service.close()
            finally:
                self._service = None
        if self._ros2_source is not None:
            try:
                self._ros2_source.close()
            finally:
                self._ros2_source = None
        self._stop_timers()
        self._snapshot = TelemetrySnapshot()
        self._last_log = "Disconnected by operator."
        self._connect_button.setEnabled(True)
        self._disconnect_button.setEnabled(False)
        self._refresh_dashboard()

    def _start_timers(self) -> None:
        poll_interval_ms = max(10, int(1000 / max(1, self._cfg.poll_hz)))
        refresh_interval_ms = max(50, int(1000 / max(1, self._cfg.refresh_hz)))
        self._poll_timer.start(poll_interval_ms)
        self._refresh_timer.start(refresh_interval_ms)
        if self._service is not None and self._cfg.heartbeat_hz > 0:
            hb_interval_ms = max(100, int(1000 / max(1, self._cfg.heartbeat_hz)))
            self._hb_timer.start(hb_interval_ms)
        else:
            self._hb_timer.stop()

    def _stop_timers(self) -> None:
        self._poll_timer.stop()
        self._hb_timer.stop()
        self._refresh_timer.stop()

    def _poll_service(self) -> None:
        if self._service is not None:
            self._service.poll(max_packets=16)
        if self._ros2_source is not None:
            self._ros2_source.poll(max_callbacks=16)
            self._snapshot = self._ros2_source.snapshot

    def _send_heartbeat(self) -> None:
        if self._service is None:
            return
        self._service.send_heartbeat(use_session=True, ack_req=False)

    def _on_status(self, st: object) -> None:
        self._snapshot.update_status(st)  # type: ignore[arg-type]

    def _on_log(self, msg: str) -> None:
        self._last_log = msg

    def _service_state(self) -> GcsServiceState:
        if self._service is not None:
            return self._service.state
        if self._ros2_source is not None:
            return self._ros2_source.state
        return GcsServiceState()

    def _refresh_dashboard(self) -> None:
        advisory_summary = ""
        advisory_recommended_action = ""
        advisory_severity = 0
        raw_frame = None
        if self._ros2_source is not None:
            self._snapshot = self._ros2_source.snapshot
            advisory = self._ros2_source.health_advisory
            advisory_summary = advisory.summary
            advisory_recommended_action = advisory.recommended_action
            advisory_severity = advisory.severity
            raw_frame = self._ros2_source.last_frame_raw
        context = OverviewContext(
            rov_addr=f"{self._cfg.rov_ip}:{self._cfg.rov_port}",
            bind_addr=f"{self._cfg.bind_ip}:{self._cfg.bind_port}",
            last_log=self._last_log,
            telemetry_source=self._cfg.telemetry_source,
            advisory_summary=advisory_summary,
            advisory_recommended_action=advisory_recommended_action,
            advisory_severity=advisory_severity,
        )
        state = build_overview_state(
            self._snapshot,
            self._service_state(),
            now_ns=time.monotonic_ns(),
            context=context,
        )

        self._target_label.setText(state.header_detail)
        self._connection_card.set_state(state.connection)
        self._device_card.set_state(state.device)
        self._navigation_card.set_state(state.navigation)
        self._control_card.set_state(state.control)
        self._command_card.set_state(state.command)
        self._fault_card.set_state(state.faults)
        self._footer_label.setText(state.footer)
        self._status_label.setText(state.connection.summary)

        self._refresh_operate_tab(state)

        execution_cards = build_execution_cards(raw_frame, self._snapshot)
        self._execution_intent_card.set_state(execution_cards[0])
        self._execution_output_card.set_state(execution_cards[1])
        self._execution_link_card.set_state(execution_cards[2])

        navigation_cards = build_navigation_cards(raw_frame, self._snapshot)
        self._nav_trust_card.set_state(navigation_cards[0])
        self._nav_motion_card.set_state(navigation_cards[1])
        self._nav_pose_card.set_state(navigation_cards[2])

        self._power_card.set_state(build_power_card(raw_frame))

    def _refresh_operate_tab(self, overview_state) -> None:
        service_state = self._service_state()
        local_cmd = self._build_local_dof_command()
        remote_policy = self._remote_dvl_policy_enabled()
        if remote_policy is None:
            dvl_policy_text = "unknown"
        else:
            dvl_policy_text = "enabled" if remote_policy else "disabled"
        lane_detail = (
            f"command_lane={'ready' if self._control_ready() else 'not_ready'}\n"
            f"telemetry_source={self._cfg.telemetry_source}\n"
            f"dvl_policy={dvl_policy_text}\n"
            f"remote_mode={int(service_state.mode)} armed={int(service_state.armed)} "
            f"estop={int(service_state.estop)}\n"
            f"nav_valid={int(service_state.nav_valid)} stale={int(service_state.nav_stale)} "
            f"degraded={int(service_state.nav_degraded)}"
        )
        self._operate_lane_card.set_state(
            OverviewCardState(
                title="Operator Lane",
                summary=overview_state.control.summary,
                detail=lane_detail,
                severity=overview_state.control.severity,
            )
        )

        self._operate_command_card.set_state(
            OverviewCardState(
                title="Local DOF Intent",
                summary="Live Send" if self._live_send_check.isChecked() else "Apply On Click",
                detail=(
                    f"surge={local_cmd.surge:+.2f}  sway={local_cmd.sway:+.2f}  "
                    f"heave={local_cmd.heave:+.2f}\n"
                    f"roll={local_cmd.roll:+.2f}  pitch={local_cmd.pitch:+.2f}  "
                    f"yaw={local_cmd.yaw:+.2f}\n"
                    f"last_ack={service_state.last_ack_kind or '-'} "
                    f"code={service_state.last_ack_code if service_state.last_ack_code is not None else '-'}"
                ),
                severity="info" if self._control_ready() else "warn",
            )
        )

        controls_enabled = self._service is not None
        for widget in (
            self._manual_mode_button,
            self._auto_mode_button,
            self._failsafe_mode_button,
            self._arm_button,
            self._disarm_button,
            self._estop_button,
            self._clear_estop_button,
            self._dvl_enable_button,
            self._dvl_disable_button,
            self._apply_dof_button,
            self._zero_dof_button,
            self._live_send_check,
            *self._dof_spins.values(),
        ):
            widget.setEnabled(controls_enabled)

        self._dvl_enable_button.setEnabled(controls_enabled and remote_policy is not True)
        self._dvl_disable_button.setEnabled(controls_enabled and remote_policy is not False)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.disconnect_service()
        super().closeEvent(event)


def launch_gui(cfg: GuiConfig, *, auto_connect: bool = True, quit_after_ms: Optional[int] = None) -> int:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication([])

    window = OverviewMainWindow(cfg, auto_connect=auto_connect)
    window.show()

    if quit_after_ms is not None and quit_after_ms > 0:
        QTimer.singleShot(int(quit_after_ms), window.close)

    if owns_app:
        return app.exec()
    return 0
