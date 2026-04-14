# src/urogcs/app/tui/tui_main.py
from __future__ import annotations

import argparse

from .tui_env import TuiConfig
from .tui_loop import run_tui


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UnderWaterRobotGCS TUI.")
    parser.add_argument(
        "--debug-session",
        action="store_true",
        help="enable explicit GCS session debug logging for handshake and UDP packets",
    )
    args = parser.parse_args(argv)

    cfg = TuiConfig.from_env()
    if args.debug_session:
        cfg.session_debug = True
    return run_tui(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
