# SPDX-License-Identifier: GPL-2.0-only
"""Reject incomplete rollback inputs before touching the receiver."""
import hashlib
from pathlib import Path
import unittest

import test_maintenance
from test_maintenance import shell_path

SOURCE = (Path(__file__).resolve().parents[1] / "rollback.sh").read_text()
VALIDATION = SOURCE[SOURCE.index('[[ -s "$B/format"'):SOURCE.index('BIN_PATH=')]


class RollbackFormatTests(unittest.TestCase):
    setUp = test_maintenance.MaintenanceTests.setUp
    bash = test_maintenance.MaintenanceTests.bash

    def fixture(self):
        for name, value in {
            "format": "pi-switch-dock-rollback-v1\n",
            "release-metadata.tar.gz": "source",
            "active-release": "v0.7.19",
            "viewer-preferences/format": "pi-viewer-preferences-v1",
            "current-custom-viewer": "binary",
            "current-viewer-override.conf": "unit",
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        sums = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' +
                       p.relative_to(self.root).as_posix() + '\n'
                       for p in sorted(self.root.rglob('*')) if p.is_file())
        (self.root / 'SHA256SUMS').write_text(sums)

    def test_complete_current_archive_is_accepted(self):
        self.fixture()
        result = self.bash(VALIDATION, {'B': shell_path(self.root)})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_required_input_is_rejected(self):
        for name in ('format', 'release-metadata.tar.gz', 'active-release',
                     'viewer-preferences/format', 'SHA256SUMS'):
            with self.subTest(name=name):
                self.fixture()
                (self.root / name).unlink()
                result = self.bash(VALIDATION, {'B': shell_path(self.root)})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Incomplete project rollback archive', result.stderr)
