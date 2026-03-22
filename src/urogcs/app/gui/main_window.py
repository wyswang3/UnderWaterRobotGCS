from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from urogcs.core.service import GcsService, GcsServiceConfig, GcsServiceState
from urogcs.telemetry.model import TelemetrySnapshot
from urogcs.telemetry.ros2_mirror_source import Ros2MirrorSnapshotSource

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
        self._navigation_card = StatusCard("Navigation")
        self._control_card = StatusCard("Control")
        self._command_card = StatusCard("Command")
        self._fault_card = StatusCard("Fault Summary")
        self._footer_label = QLabel("GUI ready. Waiting for telemetry updates.")
        self._footer_label.setObjectName("FooterLabel")
        self._footer_label.setWordWrap(True)
        self._footer_label.setTextFormat(Qt.PlainText)

        self.setWindowTitle(cfg.window_title)
        self.resize(1180, 760)
        self._build_ui()
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

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.addWidget(self._connection_card, 0, 0)
        grid.addWidget(self._device_card, 0, 1)
        grid.addWidget(self._navigation_card, 0, 2)
        grid.addWidget(self._control_card, 1, 0)
        grid.addWidget(self._command_card, 1, 1)
        grid.addWidget(self._fault_card, 1, 2)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)
        layout.addLayout(header)
        layout.addLayout(grid, 1)
        layout.addWidget(self._footer_label)

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
            """
        )

    def _make_service(self) -> GcsService:
        svc_cfg = GcsServiceConfig(
            rov_ip=self._cfg.rov_ip,
            rov_port=self._cfg.rov_port,
            bind_ip=self._cfg.bind_ip,
            bind_port=self._cfg.bind_port,
            poll_hz=self._cfg.poll_hz,
            heartbeat_hz=self._cfg.heartbeat_hz,
            handshake_timeout_s=self._cfg.handshake_timeout_s,
        )
        return GcsService(svc_cfg, on_status=self._on_status, on_log=self._on_log)

    def connect_service(self) -> None:
        if self._service is not None or self._ros2_source is not None:
            return

        if self._cfg.telemetry_source == "ros2":
            self._last_log = "Connecting to ROS2 mirror..."
            self._status_label.setText("Connecting...")
            QApplication.processEvents()

            source = Ros2MirrorSnapshotSource(on_log=self._on_log)
            ok = source.start()
            if not ok:
                self._last_log = source.last_error or "ROS2 mirror source failed."
                source.close()
                self._ros2_source = None
                self._snapshot = TelemetrySnapshot()
                self._stop_timers()
                self._connect_button.setEnabled(True)
                self._disconnect_button.setEnabled(False)
                self._refresh_dashboard()
                return

            self._ros2_source = source
            self._connect_button.setEnabled(False)
            self._disconnect_button.setEnabled(True)
            self._start_timers()
            self._refresh_dashboard()
            return

        self._last_log = "Connecting to vehicle..."
        self._status_label.setText("Connecting...")
        QApplication.processEvents()

        service = self._make_service()
        ok = service.start()
        if not ok:
            self._last_log = service.last_error or "Handshake failed."
            service.close()
            self._service = None
            self._snapshot = TelemetrySnapshot()
            self._stop_timers()
            self._connect_button.setEnabled(True)
            self._disconnect_button.setEnabled(False)
            self._refresh_dashboard()
            return

        self._service = service
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
            return
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
        if self._ros2_source is not None:
            self._snapshot = self._ros2_source.snapshot
            advisory = self._ros2_source.health_advisory
            advisory_summary = advisory.summary
            advisory_recommended_action = advisory.recommended_action
            advisory_severity = advisory.severity
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
