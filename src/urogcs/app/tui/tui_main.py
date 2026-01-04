# src/urogcs/app/tui/tui_main.py
from __future__ import annotations

from .tui_env import TuiConfig
from .tui_loop import run_tui


def main() -> int:
    cfg = TuiConfig.from_env()
    return run_tui(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
