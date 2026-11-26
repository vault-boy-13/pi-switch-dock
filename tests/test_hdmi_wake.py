import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location(
    "lite_dock_hdmi", Path(__file__).resolve().parents[1] / "lite-dock-hdmi.py"
)
hdmi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hdmi)


class EndOfTest(Exception):
    pass


class HdmiWakeTests(unittest.TestCase):
    def test_hotplug_with_valid_edid_and_empty_mode_cache_is_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            drm = Path(directory)
            port = drm / "card1-HDMI-A-1"
            port.mkdir()
            (port / "status").write_text("connected\n")
            (port / "modes").touch()
            edid = bytearray(128)
            edid[:8] = bytes.fromhex("00 ff ff ff ff ff ff 00")
            edid[-1] = -sum(edid) % 256
            with patch.object(hdmi, "DRM", drm), patch.dict(
                hdmi.os.environ, {"SDL_KMSDRM_DEVICE_INDEX": "1"}
            ):
                self.assertEqual(hdmi.hdmi_ready(), ())
                (port / "edid").write_bytes(edid)
                self.assertEqual(hdmi.hdmi_ready(), (port.name,))
                (port / "status").write_text("disconnected\n")
                self.assertEqual(hdmi.hdmi_ready(), ())

    def test_audio_route_matches_either_hdmi_port(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.env"
            with patch.object(hdmi, "VIEWER_ENV", output), patch.object(hdmi, "read", return_value=""):
                for port in (1, 2):
                    connector = f"card1-HDMI-A-{port}"
                    hdmi.prepare_viewer((connector,))
                    self.assertEqual(output.read_text().splitlines(), [
                        f"AUDIODEV=plughw:CARD=vc4hdmi{port - 1},DEV=0",
                        f"LITE_DOCK_HDMI_OUTPUT={connector}",
                    ])

    def test_port_change_restarts_viewer_to_apply_new_audio_route(self):
        with (
            patch.object(hdmi, "read", return_value="LITE_DOCK_HDMI_OUTPUT=card1-HDMI-A-2\n"),
            patch.object(hdmi.subprocess, "run") as command,
        ):
            hdmi.start_viewer(("card1-HDMI-A-2",))
            hdmi.start_viewer(("card1-HDMI-A-1",))
        self.assertEqual([call.args[0][1] for call in command.call_args_list], ["start", "restart"])

    def test_waits_until_first_mode_then_starts_viewer(self):
        # No monitor at boot, Switch arrives, HDMI appears much later.
        ready = ("card1-HDMI-A-2",)
        with (
            patch.object(hdmi, "hdmi_ready", side_effect=[(), (), (), (), ready, ready]),
            patch.object(hdmi, "switch_connected", side_effect=[False, True, True, True, True]),
            patch.object(hdmi, "wake_tv") as wake,
            patch.object(hdmi.subprocess, "run") as command,
            patch.object(hdmi.time, "monotonic", side_effect=[0, 2, 4, 36000, 36002]),
            patch.object(hdmi.time, "sleep", side_effect=[None] * 4 + [EndOfTest]),
            patch.object(hdmi, "MediaLog", return_value=Mock(media=Mock(
                side_effect=[False, False, False, False, True]
            ))),
        ):
            with self.assertRaises(EndOfTest):
                hdmi.run()
        self.assertEqual([c.args[0] for c in wake.call_args_list], [
            "dock startup", "Switch USB connected; waiting for HDMI",
        ])
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0][-2:], ["--no-block", hdmi.VIEWER])

    def test_wakes_once_on_media_when_hdmi_already_ready(self):
        ready = ("card1-HDMI-A-2",)
        with (
            patch.object(hdmi, "hdmi_ready", return_value=ready),
            patch.object(hdmi, "switch_connected", return_value=True),
            patch.object(hdmi, "wake_tv") as wake,
            patch.object(hdmi.subprocess, "run"),
            patch.object(hdmi.time, "monotonic", side_effect=[0, 2, 4, 6]),
            patch.object(hdmi.time, "sleep", side_effect=[None] * 3 + [EndOfTest]),
            patch.object(hdmi, "MediaLog", return_value=Mock(media=Mock(
                side_effect=[False, True, True, True]
            ))),
        ):
            with self.assertRaises(EndOfTest):
                hdmi.run()
        self.assertEqual([c.args for c in wake.call_args_list], [
            ("dock startup", ready), ("Switch media started", ready),
        ])

    def test_media_log_ignores_old_data_and_handles_rotation(self):
        picture = "[ 1.0 s] decoded 60.0 fps, shown 60.0 fps, skipped 0 | audio 0 KB/s\n"
        no_media = "[ 1.0 s] decoded 60.0 fps, shown 0.0 fps, skipped 1 | audio 0 KB/s\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "viewer.log"
            path.write_text(picture)
            reader = hdmi.MediaLog(path)
            self.assertFalse(reader.media())
            with path.open("a") as stream:
                stream.write(no_media + picture.rstrip())
            self.assertFalse(reader.media())
            with path.open("a") as stream:
                stream.write("\n")
            self.assertTrue(reader.media())
            self.assertFalse(reader.media())
            path.rename(path.with_suffix(".prev"))
            path.write_text(picture.replace("shown 60", "shown 0").replace("audio 0", "audio 189"))
            self.assertTrue(reader.media())
