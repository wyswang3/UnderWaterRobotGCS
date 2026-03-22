from __future__ import annotations

import unittest

from urogcs.control.keyboard_mapper import KeyboardMapper, KeyProfile


class KeyboardMapperTests(unittest.TestCase):
    def test_discrete_key_does_not_hold_motion_command(self) -> None:
        mapper = KeyboardMapper(profile=KeyProfile(step=0.5, decay=0.5, max_abs=1.0))

        cmd = mapper.update({"w"})
        self.assertAlmostEqual(cmd.surge, 0.5)

        cmd = mapper.update({","})
        self.assertAlmostEqual(cmd.surge, 0.25)
        self.assertAlmostEqual(cmd.sway, 0.0)

    def test_multiple_motion_keys_decay_instead_of_combining(self) -> None:
        mapper = KeyboardMapper(profile=KeyProfile(step=0.5, decay=0.5, max_abs=1.0))

        cmd = mapper.update({"w"})
        self.assertAlmostEqual(cmd.surge, 0.5)

        cmd = mapper.update({"w", "a"})
        self.assertAlmostEqual(cmd.surge, 0.25)
        self.assertAlmostEqual(cmd.sway, 0.0)


if __name__ == "__main__":
    unittest.main()
