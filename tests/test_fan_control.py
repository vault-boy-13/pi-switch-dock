# SPDX-License-Identifier: GPL-2.0-only
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "switch_dock_fan", ROOT / "switch-dock-fan.py")
fan = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {"lgpio": ModuleType("lgpio")}):
    SPEC.loader.exec_module(fan)


class FanControlTests(unittest.TestCase):
    def run_main_once(self, temperature=None, error=None):
        gpio = Mock()
        gpio.gpiochip_open.return_value = 1
        gpio.gpio_claim_output.return_value = 0
        gpio.tx_pwm.return_value = 0
        fan.running = True
        read = patch.object(fan, "read_temperature", side_effect=[error, temperature]
                            if error else [temperature])
        with patch.object(fan, "lgpio", gpio), patch.object(fan.signal, "signal"), \
                patch.object(fan.time, "sleep", side_effect=lambda _seconds: fan.request_stop(None, None)), \
                read:
            fan.main()
        return gpio

    def test_idle_threshold_and_minimum_running_duty(self):
        self.assertEqual(fan.STATES[fan.state_for_temperature(54_999)], ("off", 0))
        self.assertEqual(fan.STATES[fan.state_for_temperature(55_000)], ("low", 25))
        self.assertTrue(all(duty >= 25 for name, duty in fan.STATES if name != "off"))

    def test_idle_startup_and_shutdown_do_not_kick_fan(self):
        gpio = self.run_main_once(50_000)
        self.assertEqual([call.args[3] for call in gpio.tx_pwm.call_args_list], [0, 0])
        gpio.gpio_claim_output.assert_called_once_with(1, fan.GPIO, 0)

    def test_full_duty_is_used_only_at_high_temperature(self):
        gpio = self.run_main_once(70_000)
        self.assertEqual([call.args[3] for call in gpio.tx_pwm.call_args_list], [100, 0])

    def test_sensor_error_uses_minimum_speed_and_stops_cleanly(self):
        gpio = self.run_main_once(temperature=None, error=OSError("missing sensor"))
        self.assertEqual([call.args[3] for call in gpio.tx_pwm.call_args_list], [25, 0])

    def test_service_keeps_gpio_low_before_start_and_after_stop(self):
        service = (ROOT / "switch-dock-fan.service").read_text()
        self.assertIn("ExecStartPre=/usr/bin/pinctrl set 18 op dl", service)
        self.assertIn("ExecStopPost=/usr/bin/pinctrl set 18 op dl", service)

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
