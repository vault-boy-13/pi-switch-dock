# SPDX-License-Identifier: GPL-2.0-only
"""Execute fresh-install unit generation/activation in an isolated directory."""
from pathlib import Path
import unittest

import test_maintenance
from test_maintenance import shell_path, SOURCE


class BootstrapTests(unittest.TestCase):
    setUp = test_maintenance.MaintenanceTests.setUp
    bash = test_maintenance.MaintenanceTests.bash

    def prepare(self, name, connector, audio):
        root = self.root / name
        drm = root / "drm"
        target = drm / connector
        target.mkdir(parents=True)
        (target / "status").write_text("connected\n")
        # An unrelated, disconnected output must not steal the selection.
        other = drm / "card9-HDMI-A-1"
        other.mkdir()
        (other / "status").write_text("disconnected\n")
        cards = root / "cards"
        cards.write_text(audio)
        unit = root / "systemd/viewer.service"
        dropin = root / "systemd/viewer.service.d/candidate.conf"
        start = SOURCE.index('    CONNECTED=""\n', SOURCE.index('if (( BOOTSTRAP )); then\n    CONNECTED='))
        end = SOURCE.index('\nelse\n    BACKUP_DIR=', start)
        code = SOURCE[start:end].replace("/sys/class/drm", shell_path(drm)).replace(
            "/proc/asound/cards", shell_path(cards))
        env = {"UNIT": shell_path(unit), "DROPIN": shell_path(dropin), "NEW_BIN": "/candidate",
               "SERVICE": "switch-frame-tap-viewer.service", "BOOTSTRAP": "1"}
        return unit, dropin, code, env

    def test_fresh_install_has_complete_runtime_policy_and_boot_enablement(self):
        for name, connector, index, audio in (
            ("hdmi1", "card1-HDMI-A-1", "1", "vc4hdmi0"),
            ("hdmi2", "card5-HDMI-A-2", "5", "vc4hdmi1"),
        ):
            with self.subTest(output=connector):
                unit, dropin, code, env = self.prepare(name, connector, audio)
                # Run the actual activation branch too, with systemd mocked.
                start = SOURCE.index('cat > "$DROPIN" <<EOF\n[Service]')
                end = SOURCE.index('wait_for_viewer "$NEW_BIN"\n', start) + len('wait_for_viewer "$NEW_BIN"\n')
                result = self.bash('systemctl() { echo "systemctl $*"; }\n'
                                   'wait_for_viewer() { echo "verified $1"; }\n'
                                   + code + '\n' + SOURCE[start:end], env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("systemctl enable --now switch-frame-tap-viewer.service", result.stdout)
                self.assertIn("verified /candidate", result.stdout)
                for path in (unit, dropin):
                    content = path.read_text()
                    self.assertIn("ExecStart=/candidate --app --fullscreen --hwdec", content)
                    for setting in ("SFT_KMS_SCANOUT=0", "SFT_SCANOUT_PACING=0", "SFT_DISPLAY_POLICY=auto"):
                        self.assertIn("Environment=" + setting, content)
                content = unit.read_text()
                self.assertIn("Environment=HOME=/root", content)
                self.assertIn("Environment=XDG_DATA_HOME=/root/.local/share", content)
                self.assertIn("Environment=SDL_KMSDRM_DEVICE_INDEX=" + index, content)
                self.assertIn("Environment=AUDIODEV=plughw:CARD=" + audio + ",DEV=0", content)
                self.assertIn("WantedBy=multi-user.target", content)
                self.assertIn("After=systemd-logind.service lite-dock-splash.service", content)
                self.assertIn("ExecStartPre=-/usr/bin/systemctl stop lite-dock-splash.service", content)
                self.assertNotIn("Wants=lite-dock-splash.service", content)

    def test_missing_hdmi_audio_does_not_create_a_partial_service(self):
        unit, dropin, code, env = self.prepare("missing-audio", "card1-HDMI-A-1", "Headphones only")
        result = self.bash(code, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HDMI audio device vc4hdmi0 was not found", result.stderr)
        self.assertFalse(unit.exists())
        self.assertFalse(dropin.exists())


if __name__ == "__main__":
    unittest.main()
