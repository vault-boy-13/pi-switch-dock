# SPDX-License-Identifier: GPL-2.0-only
"""Exercise patch rejection and build identity without touching the receiver."""
from pathlib import Path
import hashlib
import re
import unittest

import test_maintenance
from test_maintenance import function, shell_path

def patch_function():
    source = (Path(__file__).resolve().parents[1] / "build-receiver.sh").read_text()
    return re.search(r"^apply_pi_patches\(\) \{\n.*?^\}", source, re.M | re.S)[0]


class PatchStackTests(unittest.TestCase):
    setUp = test_maintenance.MaintenanceTests.setUp
    bash = test_maintenance.MaintenanceTests.bash

    def test_patch_failure_stops_before_later_patches(self):
        source = self.root / "source"
        patches = self.root / "patches"
        source.mkdir()
        patches.mkdir()
        (source / "viewer.c").write_text("upstream changed\n")
        (patches / "bad.patch").write_text(
            "--- a/viewer.c\n+++ b/viewer.c\n@@ -1 +1 @@\n-old\n+patched\n")
        (patches / "later.patch").write_text("should never be read")
        result = self.bash('PI_PATCHES=(bad.patch later.patch)\n' + patch_function()
                           + '\napply_pi_patches\necho activated\n', {
            "SRC": shell_path(source), "PATCH_DIR": shell_path(patches), "TAG": "v9.0.0",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((source / "viewer.c").read_text(), "upstream changed\n")
        self.assertNotIn("later.patch", result.stdout)
        self.assertNotIn("activated", result.stdout)
        self.assertIn("Current receiver was not replaced", result.stderr)

    def test_fuzz_is_rejected(self):
        source = self.root / "source"
        source.mkdir()
        (source / "viewer.c").write_text("different context\nold\nend\n")
        (self.root / "change.patch").write_text(
            "--- a/viewer.c\n+++ b/viewer.c\n@@ -1,3 +1,3 @@\n original context\n-old\n+new\n end\n")
        result = self.bash('PI_PATCHES=(change.patch)\n' + patch_function()
                           + '\napply_pi_patches', {
            "SRC": shell_path(source), "PATCH_DIR": shell_path(self.root), "TAG": "v9.0.0",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("old", (source / "viewer.c").read_text())

    def test_identity_requires_matching_patches_binary_and_runtime(self):
        source = self.root / "source"
        source.mkdir()
        binary = self.root / "viewer"
        binary.write_bytes(b"known validated receiver")
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        runtime = "SFT_KMS_SCANOUT=0 SFT_SCANOUT_PACING=0 SFT_DISPLAY_POLICY=auto"
        mocks = '''
fullscreen_configured() { return 0; }
systemctl() {
    case "$3" in
        ExecStart) echo "$VIEWER_COMMAND" ;;
        Environment) echo "$VIEWER_ENV" ;;
        MainPID) echo 123 ;;
    esac
}
readlink() { if [[ "$2" == /proc/* ]]; then echo "$VIEWER_BINARY"; else echo "$VIEWER_SOURCE"; fi; }
'''
        for label, metadata, command, environment, accepted in (
            ("valid", f"v0.7.19 stack1 {digest}", "viewer --app --hwdec", runtime, True),
            ("no pacing", f"v0.7.19 stack1 {digest}", "viewer --app --hwdec", "SFT_KMS_SCANOUT=0 SFT_DISPLAY_POLICY=auto", False),
            ("no display policy", f"v0.7.19 stack1 {digest}", "viewer --app --hwdec", "SFT_KMS_SCANOUT=0 SFT_SCANOUT_PACING=0", False),
            ("old patches", f"v0.7.19 stack0 {digest}", "viewer --app --hwdec", "SFT_KMS_SCANOUT=0", False),
            ("other binary", "v0.7.19 stack1 deadbeef", "viewer --app --hwdec", "SFT_KMS_SCANOUT=0", False),
            ("old release", f"v0.7.18 stack1 {digest}", "viewer --app --hwdec", "SFT_KMS_SCANOUT=0", False),
            ("no hwdec", f"v0.7.19 stack1 {digest}", "viewer", "SFT_KMS_SCANOUT=0", False),
            ("no app", f"v0.7.19 stack1 {digest}", "viewer --hwdec", "SFT_KMS_SCANOUT=0", False),
            ("scanout enabled", f"v0.7.19 stack1 {digest}", "viewer --app --hwdec", "SFT_KMS_SCANOUT=1 SFT_SCANOUT_PACING=0 SFT_DISPLAY_POLICY=auto", False),
            ("pacing enabled", f"v0.7.19 stack1 {digest}", "viewer --app --hwdec", "SFT_KMS_SCANOUT=0 SFT_SCANOUT_PACING=1 SFT_DISPLAY_POLICY=auto", False),
            ("no identity", None, "viewer --app --hwdec", "SFT_KMS_SCANOUT=0", False),
        ):
            with self.subTest(label=label):
                marker = source / ".pi-build"
                if metadata is None:
                    marker.unlink(missing_ok=True)
                else:
                    marker.write_text(metadata + "\n")
                result = self.bash(mocks + function("pi_stack_configured") + '\npi_stack_configured', {
                    "SERVICE": "viewer", "SOURCE_LINK": "/current", "DOCK_VERSION": "v0.7.19",
                    "PI_STACK_HASH": "stack1", "VIEWER_BINARY": shell_path(binary),
                    "VIEWER_SOURCE": shell_path(source), "VIEWER_COMMAND": command,
                    "VIEWER_ENV": environment,
                })
                self.assertEqual(result.returncode == 0, accepted, result.stderr)


if __name__ == "__main__":
    unittest.main()
