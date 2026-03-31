from __future__ import annotations

import os
import unittest

from urogcs.app.gui.gui_env import GuiConfig


class GuiEnvTests(unittest.TestCase):
    def test_gui_defaults_use_ephemeral_bind_port(self) -> None:
        cfg = GuiConfig()
        self.assertEqual(cfg.bind_port, 0)

    def test_gui_env_allows_independent_bind_port_override(self) -> None:
        old = dict(os.environ)
        try:
            os.environ.pop("UROGCS_BIND_PORT", None)
            os.environ.pop("UROGCS_GUI_BIND_PORT", None)

            cfg = GuiConfig.from_env()
            self.assertEqual(cfg.bind_port, 0)

            os.environ["UROGCS_BIND_PORT"] = "14551"
            cfg = GuiConfig.from_env()
            self.assertEqual(cfg.bind_port, 14551)

            os.environ["UROGCS_GUI_BIND_PORT"] = "0"
            cfg = GuiConfig.from_env()
            self.assertEqual(cfg.bind_port, 0)
        finally:
            os.environ.clear()
            os.environ.update(old)

