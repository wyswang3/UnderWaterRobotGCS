from __future__ import annotations

import argparse
import os
import sys

from urogcs.app.gui.gui_env import GuiConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UnderWaterRobotGCS PySide6 overview dashboard.")
    parser.add_argument(
        "--no-auto-connect",
        action="store_true",
        help="start the GUI without attempting the initial handshake",
    )
    parser.add_argument(
        "--quit-after-ms",
        type=int,
        default=None,
        help="developer smoke-test helper for headless/offscreen launch validation",
    )
    parser.add_argument(
        "--telemetry-source",
        choices=["udp", "ros2"],
        default=None,
        help="select the dashboard data source; ROS2 is a read-only mirror preview path",
    )
    parser.add_argument(
        "--debug-session",
        action="store_true",
        help="enable explicit GCS session debug logging for handshake and UDP packets",
    )
    args = parser.parse_args(argv)

    try:
        from urogcs.app.gui.main_window import launch_gui
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            print("[GUI] PySide6 is not installed in this environment.", file=sys.stderr)
            print("[GUI] Install it with: python3 -m pip install PySide6", file=sys.stderr)
            return 2
        raise

    cfg = GuiConfig.from_env()
    if args.telemetry_source is not None:
        cfg.telemetry_source = args.telemetry_source
    if args.debug_session:
        cfg.session_debug = True
    auto_connect = cfg.auto_connect and not args.no_auto_connect

    # Allow CI/headless smoke tests to request a finite GUI lifetime without
    # introducing a second launch entry point.
    quit_after_ms = args.quit_after_ms
    if quit_after_ms is None:
        quit_env = os.getenv("UROGCS_GUI_QUIT_AFTER_MS", "").strip()
        if quit_env:
            try:
                quit_after_ms = int(quit_env)
            except ValueError:
                quit_after_ms = None

    return launch_gui(cfg, auto_connect=auto_connect, quit_after_ms=quit_after_ms)


if __name__ == "__main__":
    raise SystemExit(main())
