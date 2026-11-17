# SPDX-License-Identifier: GPL-2.0-only
"""Run on Linux: python3 -m unittest discover -s tests -v."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / "deploy.sh").read_text()


def shell_path(path):
    value = Path(path).resolve().as_posix()
    if os.name == "nt":  # Git Bash paths for local Windows checks.
        return "/" + value[0].lower() + value[2:]
    return value


def function(name):
    return re.search(r"^" + name + r"\(\) \{\n.*?^\}", SOURCE, re.M | re.S)[0]


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dock-tests-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def bash(self, code, env=None):
        return subprocess.run([os.environ.get("TEST_BASH", "bash"), "-c", "set -Eeuo pipefail\n" + code],
                              env={**os.environ, **(env or {})}, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def fixture(self):
        for folder in ("builds", "backups", "bin", "work"):
            (self.root / folder).mkdir()
        names = [f"20261025-1200{i:02d}-v0.7.{i}" for i in range(10)]
        bins = [f"switch-frame-tap-viewer-v0.7.{i}-v4l2-20261025-1200{i:02d}"
                for i in range(10)]
        for name, binary in zip(names, bins):
            (self.root / "builds" / name / "release").mkdir(parents=True)
            (self.root / "bin" / binary).write_text("viewer")
            (self.root / "backups" / (name + ".tar.gz")).write_text("obsolete")
        backup = self.root / "backups" / names[-1]
        backup.mkdir()
        previous_bin = shell_path(self.root / "bin" / bins[-2])
        previous_source = shell_path(self.root / "builds" / names[-2] / "release")
        (backup / "active-binary-path").write_text(previous_bin + "\n", newline="\n")
        (backup / "active-source-path").write_text(previous_source + "\n", newline="\n")
        (backup / "current-custom-viewer").write_text("backup viewer")
        sums = "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
                       for p in sorted(backup.iterdir()))
        (backup / "SHA256SUMS").write_text(sums, newline="\n")
        archive = backup.with_suffix(backup.suffix + ".tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(backup, arcname=backup.name)
        env = dict(BUILD_ROOT=shell_path(self.root / "builds"),
                   BACKUP_ROOT=shell_path(self.root / "backups"),
                   BIN_ROOT=shell_path(self.root / "bin"), WORK=shell_path(self.root / "work"),
                   ROLLBACK_ARCHIVE=shell_path(archive),
                   BUILD_DIR=shell_path(self.root / "builds" / names[-1]),
                   NEW_BIN=shell_path(self.root / "bin" / bins[-1]))
        return env, names, bins, archive

    def test_ten_updates_leave_one_archive_and_two_builds(self):
        env, names, bins, archive = self.fixture()
        result = self.bash(function("prune_previous_versions") + "\nprune_previous_versions", env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list((self.root / "backups").iterdir()), [archive])
        self.assertEqual(sorted(p.name for p in (self.root / "builds").iterdir()), names[-2:])
        self.assertEqual(sorted(p.name for p in (self.root / "bin").iterdir()), bins[-2:])
        # Cleanup is repeatable after removing the unpacked backup directory.
        result = self.bash(function("prune_previous_versions") + "\nprune_previous_versions", env)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_corrupt_archive_does_not_prune(self):
        env, names, _, archive = self.fixture()
        archive.write_bytes(b"broken")
        result = self.bash(function("prune_previous_versions") + "\nprune_previous_versions", env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(list((self.root / "builds").iterdir())), len(names))
        self.assertEqual(len(list((self.root / "backups").iterdir())), 11)

    def test_symlinks_and_unrelated_data_are_preserved(self):
        env, _, _, _ = self.fixture()
        external = self.root / "external"
        external.mkdir()
        (external / "keep").write_text("keep")
        link = self.root / "builds" / "20200101-000000-v0.0.1"
        try:
            link.symlink_to(external, target_is_directory=True)
        except OSError as error:
            if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows account cannot create symbolic links; run this check on Linux.")
            raise
        (self.root / "backups" / "personal-notes").write_text("keep")
        result = self.bash(function("prune_previous_versions") + "\nprune_previous_versions", env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(link.is_symlink())
        self.assertTrue((external / "keep").is_file())
        self.assertTrue((self.root / "backups" / "personal-notes").is_file())

    def test_bad_checksum_does_not_prune(self):
        env, names, _, archive = self.fixture()
        backup = archive.parent / archive.name.removesuffix(".tar.gz")
        (backup / "current-custom-viewer").write_text("corrupt")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(backup, arcname=backup.name)
        result = self.bash(function("prune_previous_versions") + "\nprune_previous_versions", env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(list((self.root / "builds").iterdir())), len(names))

    def test_stable_viewer_is_accepted(self):
        mocks = '''
systemctl() { if [[ "$1" == show ]]; then echo 123; fi; }
readlink() { echo /viewer; }
sleep() { :; }
journalctl() { :; }
SERVICE=test
'''
        result = self.bash(mocks + function("wait_for_viewer") + '\nwait_for_viewer /viewer')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_restart_loop_is_rejected(self):
        counter = self.root / "counter"
        counter.write_text("0")
        mocks = '''
systemctl() {
    if [[ "$1" == show ]]; then
        n=$(cat "$COUNTER"); n=$((n+1)); echo "$n" > "$COUNTER"; echo "$n"
    fi
}
readlink() { echo /viewer; }
sleep() { :; }
journalctl() { :; }
SERVICE=test
'''
        result = self.bash(mocks + function("wait_for_viewer") + '\nwait_for_viewer /viewer',
                           {"COUNTER": shell_path(counter)})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not stay active", result.stderr)

    def test_disconnected_configured_hdmi_is_rejected(self):
        drm = self.root / "drm"
        for card, state in ((1, "disconnected"), (2, "connected")):
            connector = drm / f"card{card}-HDMI-A-1"
            connector.mkdir(parents=True)
            (connector / "status").write_text(state)
        code = function("require_hdmi").replace("/sys/class/drm", shell_path(drm))
        result = self.bash('systemctl() { echo SDL_KMSDRM_DEVICE_INDEX=1; }; sleep() { :; }; SERVICE=test\n'
                           + code + '\nrequire_hdmi')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No receiver files were changed", result.stderr)

    def commit(self, bootstrap, fail_flush=0):
        # Execute the actual commit/cleanup/success path, with no host changes.
        tail = SOURCE[SOURCE.index('wait_for_viewer "$NEW_BIN"\n'):]
        mocks = '''
wait_for_viewer() { echo stable; }
pi_stack_configured() { echo verified-pi-stack; }
activate_tools() { echo tools-activated; }
ln() { echo source-link; }
mv() { echo archive-committed; }
prune_previous_versions() { echo pruned; }
systemctl() { return 0; }
sync() {
    FLUSHES=$((FLUSHES + 1))
    echo "flush-$FLUSHES"
    if (( FLUSHES == FAIL_FLUSH )); then return 1; fi
}
rollback_on_error() { echo recovered; exit 1; }
cleanup() { :; }
FLUSHES=0
trap rollback_on_error ERR
'''
        return self.bash(mocks + function("persist_installation") + "\n" + tail, {
            "BOOTSTRAP": str(bootstrap), "FAIL_FLUSH": str(fail_flush),
            "NEW_BIN": "/viewer", "BUILD_DIR": "/build", "SOURCE_LINK": "/current",
            "STATE_FILE": shell_path(self.root / "release"), "TAG": "v0.7.19",
            "BACKUP_DIR": "/backup", "BACKUP_ROOT": shell_path(self.root / "absent"),
            "BIN_ROOT": "/bin", "BUILD_ROOT": "/builds", "STATE_DIR": "/state",
            "SERVICE": "viewer",
            "DOCK_VERSION": "v0.7.19", "BUNDLE": "/bundle",
        })

    def test_commit_flushes_before_pruning_and_success(self):
        for bootstrap in (0, 1):
            with self.subTest(bootstrap=bootstrap):
                result = self.commit(bootstrap)
                self.assertEqual(result.returncode, 0, result.stderr)
                events = result.stdout.splitlines()
                self.assertLess(events.index("source-link"), events.index("flush-1"))
                if not bootstrap:
                    self.assertLess(events.index("archive-committed"), events.index("flush-1"))
                    self.assertLess(events.index("flush-1"), events.index("pruned"))
                    self.assertLess(events.index("pruned"), events.index("flush-2"))
                self.assertLess(events.index("flush-2"), events.index("Installed pi-switch-dock v0.7.19 (Switch Frame Tap v0.7.19)."))

    def test_flush_error_never_announces_success(self):
        for bootstrap in (0, 1):
            for fail_flush in (1, 2):
                with self.subTest(bootstrap=bootstrap, fail_flush=fail_flush):
                    result = self.commit(bootstrap, fail_flush)
                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn("Installed pi-switch-dock", result.stdout)
                    self.assertNotIn("The receiver is active.", result.stdout)
                    if fail_flush == 1:
                        self.assertIn("recovered", result.stdout)
                        self.assertNotIn("pruned", result.stdout)



if __name__ == "__main__":
    unittest.main()
