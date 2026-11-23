# SPDX-License-Identifier: GPL-2.0-only
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lite_dock_cec_name", ROOT / "lite-dock-cec-name.py")
cec = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cec)


class CECNameTests(unittest.TestCase):
    def test_configures_each_adapter_with_playback_type_and_osd_name(self):
        with tempfile.TemporaryDirectory() as directory:
            devices = Path(directory)
            (devices / "cec1").touch()
            (devices / "cec0").touch()
            run = Mock()

            cec.configure_adapters(devices, run)

        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["/usr/bin/cec-ctl", "--device", str(devices / "cec0"),
                 "--playback", "--osd-name", "Lite Dock"],
                ["/usr/bin/cec-ctl", "--device", str(devices / "cec1"),
                 "--playback", "--osd-name", "Lite Dock"],
            ],
        )
        self.assertTrue(all(call.kwargs == {"check": True} for call in run.call_args_list))

    def test_missing_adapters_are_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Mock()
            cec.configure_adapters(Path(directory), run)
        run.assert_not_called()

    def test_fails_if_no_adapter_can_be_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "cec0").touch()
            run = Mock(side_effect=subprocess.CalledProcessError(1, "cec-ctl"))
            with self.assertRaisesRegex(RuntimeError, "Could not configure any"):
                cec.configure_adapters(Path(directory), run)

    def test_one_unavailable_adapter_does_not_block_another(self):
        with tempfile.TemporaryDirectory() as directory:
            devices = Path(directory)
            (devices / "cec0").touch()
            (devices / "cec1").touch()
            run = Mock(side_effect=[subprocess.CalledProcessError(1, "cec-ctl"), None])

            cec.configure_adapters(devices, run)

        self.assertEqual(run.call_count, 2)

    def test_unit_waits_for_udev_and_runs_before_the_receiver(self):
        service = (ROOT / "lite-dock-cec-name.service").read_text()
        self.assertIn("After=systemd-udev-settle.service", service)
        self.assertIn("Before=switch-frame-tap-viewer.service", service)
        self.assertIn("WantedBy=multi-user.target", service)


if __name__ == "__main__":
    unittest.main()
