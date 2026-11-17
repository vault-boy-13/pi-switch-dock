# SPDX-License-Identifier: GPL-2.0-only
"""Preferences rollback must handle the live root path and absent SDL files."""
from pathlib import Path
import shlex
import unittest

import test_maintenance
from test_maintenance import shell_path


HELPER = (Path(__file__).resolve().parents[1] / "viewer-config.sh").read_text()


class ViewerConfigTests(unittest.TestCase):
    setUp = test_maintenance.MaintenanceTests.setUp
    bash = test_maintenance.MaintenanceTests.bash

    def code(self):
        return HELPER + '\nPI_VIEWER_CONFIG_PATH=' + shlex.quote(shell_path(self.root / "viewer.ini")) + '\n'

    def test_restore_preserves_actual_root_preferences_and_absence(self):
        original = b"hwdec=1\nlock_aspect=1\nvsync=0\n"
        (self.root / "viewer.ini").write_bytes(original)
        result = self.bash(self.code() + '''
save_viewer_preferences "$SAVED"
printf 'changed' > "$PI_VIEWER_CONFIG_PATH"
restore_viewer_preferences "$SAVED"
''', {"SAVED": shell_path(self.root / "saved")})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "viewer.ini").read_bytes(), original)

    def test_refresh_snapshot_records_file_removed_after_exit(self):
        (self.root / "viewer.ini").write_text("original")
        result = self.bash(self.code() + '''
save_viewer_preferences "$SAVED"
rm "$PI_VIEWER_CONFIG_PATH"
save_viewer_preferences "$SAVED"
printf 'candidate' > "$PI_VIEWER_CONFIG_PATH"
restore_viewer_preferences "$SAVED"
''', {"SAVED": shell_path(self.root / "saved")})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "viewer.ini").exists())

    def test_incomplete_snapshot_cannot_remove_preferences(self):
        (self.root / "viewer.ini").write_text("keep")
        result = self.bash(self.code() + '\nrestore_viewer_preferences "$SAVED"',
                           {"SAVED": shell_path(self.root / "missing")})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / "viewer.ini").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
