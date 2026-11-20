# SPDX-License-Identifier: GPL-2.0-only
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "switch_dock_fan", ROOT / "switch-dock-fan.py")
fan = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {"lgpio": ModuleType("lgpio")}):
    SPEC.loader.exec_module(fan)


class FanControlTests(unittest.TestCase):
    def test_idle_threshold_and_minimum_running_duty(self):
        self.assertEqual(fan.STATES[fan.state_for_temperature(54_999)], ("off", 0))
        self.assertEqual(fan.STATES[fan.state_for_temperature(55_000)], ("low", 25))
        self.assertTrue(all(duty >= 25 for name, duty in fan.STATES if name != "off"))

    def test_temperature_rises_through_each_fan_stage(self):
        for temperature, expected in (
            (55_000, 1),
            (60_000, 2),
            (65_000, 3),
            (70_000, 4),
        ):
            with self.subTest(temperature=temperature):
                self.assertEqual(fan.state_for_temperature(temperature), expected)

    def test_hysteresis_keeps_speed_until_the_lower_threshold(self):
        self.assertEqual(fan.hysteresis_state(1, 50_000), 1)
        self.assertEqual(fan.hysteresis_state(1, 49_999), 0)
        self.assertEqual(fan.hysteresis_state(2, 58_000), 2)
        self.assertEqual(fan.hysteresis_state(2, 57_999), 1)


if __name__ == "__main__":
    unittest.main()
