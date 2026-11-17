# SPDX-License-Identifier: GPL-2.0-only
"""Boot configuration checks use temporary files, never the live Pi config."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from boot_config import configure, prepare


class BootConfigTests(unittest.TestCase):
    def test_settings_in_other_model_do_not_satisfy_pi4(self):
        original = "[pi5]\ndtoverlay=vc4-kms-v3d\ndtoverlay=dwc2,dr_mode=host\n"
        result = prepare(original)
        self.assertTrue(result.startswith(original))
        self.assertIn("[all]\n# Switch Frame Tap", result)
        self.assertEqual(result.count("dtoverlay=dwc2,dr_mode=host"), 2)
        self.assertEqual(prepare(result), result)

    def test_existing_pi4_settings_are_preserved(self):
        text = "[pi4]\ndtoverlay=vc4-kms-v3d,cma-256\ndtoverlay=dwc2,dr_mode=host\n[cm4]\notg_mode=1\n"
        self.assertEqual(prepare(text), text)

    def test_only_missing_setting_is_added(self):
        result = prepare("dtoverlay=vc4-kms-v3d\n[pi5]\n")
        self.assertEqual(result.count("dtoverlay=vc4-kms-v3d"), 1)
        self.assertEqual(result.count("dtoverlay=dwc2,dr_mode=host"), 1)

    def test_conflicts_are_rejected(self):
        for setting in ("dtoverlay=vc4-fkms-v3d", "dtoverlay=dwc2",
                        "dtoverlay=dwc2,dr_mode=peripheral", "otg_mode=1",
                        "dtoverlay=vc4-kms-v3d,noaudio"):
            with self.subTest(setting=setting), self.assertRaises(ValueError):
                prepare(setting + "\n")

    def test_accumulated_filters_are_not_mistaken_for_pi4(self):
        with self.assertRaises(ValueError):
            prepare("[EDID=example]\n[pi4]\ndtoverlay=vc4-kms-v3d\n")

    def test_all_resets_other_filters(self):
        text = "[EDID=example]\n[pi3]\n[all]\ndtoverlay=vc4-kms-v3d\ndtoverlay=dwc2,dr_mode=host\n"
        self.assertEqual(prepare(text), text)

    def test_includes_are_rejected(self):
        for directive in ("include extra.txt", "include\textra.txt"):
            with self.subTest(directive=directive), self.assertRaises(ValueError):
                prepare(directive + "\n")

    def test_duplicate_overlays_are_rejected(self):
        with self.assertRaises(ValueError):
            prepare("dtoverlay=vc4-kms-v3d\n[pi4]\ndtoverlay=vc4-kms-v3d\n")

    def test_backup_contains_original_bytes_and_repeat_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.txt"
            backups = Path(tmp) / "backups"
            original = b"# custom\n[pi5]\ndtparam=audio=on\n"
            config.write_bytes(original)
            self.assertTrue(configure(config, backups))
            self.assertEqual(next(backups.iterdir()).read_bytes(), original)
            self.assertFalse(configure(config, backups))
            self.assertEqual(len(list(backups.iterdir())), 1)

    def test_conflict_does_not_write_or_create_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.txt"
            backups = Path(tmp) / "backups"
            original = b"dtoverlay=dwc2,dr_mode=peripheral\n"
            config.write_bytes(original)
            with self.assertRaises(ValueError):
                configure(config, backups)
            self.assertEqual(config.read_bytes(), original)
            self.assertFalse(backups.exists())


if __name__ == "__main__":
    unittest.main()
