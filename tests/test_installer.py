# SPDX-License-Identifier: GPL-2.0-only
"""The public bootstrap must resolve a stable project release before setup."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class InstallerTests(unittest.TestCase):
    def test_bootstrap_is_project_only_and_tag_pinned(self):
        source = (ROOT / "install.sh").read_text()
        self.assertIn("api.github.com/repos/vault-boy-13/pi-switch-dock/releases/latest", source)
        self.assertIn('pi-switch-dock/$TAG/release_client.py', source)
        self.assertNotIn("TomasUribe", source)
        self.assertNotIn("/main/", source)

    def test_receiver_build_uses_pinned_source_and_our_build_script(self):
        source = (ROOT / "deploy.sh").read_text()
        self.assertIn('prepare-source.py', source)
        self.assertIn('bash "$BUNDLE/build-receiver.sh" "$SRC" "$TAG"', source)
        self.assertIn('BUILT_BIN="$SRC/tools/raw-recv/raw-view"', source)

    def test_initial_setup_installs_temperature_controlled_fan(self):
        source = (ROOT / "setup.sh").read_text()
        self.assertIn('python3-lgpio', source)
        self.assertIn('bash "$BUNDLE/install-fan.sh"', source)
        self.assertIn('"switch-dock-fan.py"', (ROOT / "release_client.py").read_text())

if __name__ == "__main__":
    unittest.main()
