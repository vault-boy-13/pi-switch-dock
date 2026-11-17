# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual initial installer with isolated paths and mocked hardware."""
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import struct
import sys
import unittest

import test_maintenance
from test_maintenance import shell_path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("presentation", ROOT / "splash/boot-presentation.py")
presentation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(presentation)
BASE = ("console=serial0,115200 console=tty1 root=PARTUUID=keep-this-02 "
        "rootfstype=ext4 fsck.repair=yes rootwait ds=nocloud;i=keep-this "
        "cfg80211.ieee80211_regdom=RU\n")


class PresentationTests(unittest.TestCase):
    def test_boot_preserves_root_consoles_fsck_and_network_arguments(self):
        updated = presentation.prepare_cmdline(BASE)
        self.assertEqual(updated.split()[:len(BASE.split())], BASE.split())
        self.assertEqual(updated, presentation.prepare_cmdline(updated))
        for item in presentation.OPTIONS:
            self.assertEqual(updated.split().count(item), 1)
        self.assertNotIn("splash", updated.split())

    def test_ambiguous_or_recovery_boot_is_rejected(self):
        for value in (BASE + "extra\n", BASE.replace("console=tty1 ", ""),
                      BASE.replace("root=PARTUUID=keep-this-02 ", ""),
                      BASE.strip() + " init=/bin/sh", BASE.strip() + " fbcon=map:0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                presentation.prepare_cmdline(value)

    def test_assets_are_original_bmp_v4_with_alpha(self):
        for name, dimensions in (("card", (640, 320)), ("halo", (64, 64)),
                                 ("dot", (20, 20)), ("bar", (30, 3))):
            data = (ROOT / f"splash/{name}.bmp").read_bytes()
            self.assertEqual(data[:2], b"BM")
            self.assertEqual(struct.unpack_from("<I", data, 10)[0], 122)
            self.assertEqual(struct.unpack_from("<ii", data, 18), dimensions)
            self.assertEqual(struct.unpack_from("<I", data, 66)[0], 0xff000000)


class SplashInstallTests(unittest.TestCase):
    setUp = test_maintenance.MaintenanceTests.setUp
    bash = test_maintenance.MaintenanceTests.bash

    def prepare(self, existing_receiver=False):
        firmware = self.root / "boot/firmware"
        firmware.mkdir(parents=True)
        (firmware / "cmdline.txt").write_text(BASE, newline="\n")
        (firmware / "config.txt").write_text("[all]\ndtoverlay=vc4-kms-v3d\n", newline="\n")
        unit = self.root / "etc/systemd/system/switch-frame-tap-viewer.service"
        unit.parent.mkdir(parents=True)
        if existing_receiver:
            unit.write_text("existing receiver")
        drm = self.root / "sys/class/drm/card5-HDMI-A-2"
        drm.mkdir(parents=True)
        (drm / "status").write_text("connected\n")
        code = (ROOT / "install-splash.sh").read_text()
        start = code.index('BUNDLE=')
        end = code.index('\n', start)
        code = code[:start] + 'BUNDLE="' + shell_path(ROOT) + '"' + code[end:]
        code = code.replace(' && $EUID == 0', '')
        prefixes = ("/var/lib", "/usr/local", "/etc/systemd/system", "/boot/firmware", "/sys/class", "/tmp")
        code = re.sub("|".join(map(re.escape, prefixes)),
                      lambda match: shell_path(self.root) + match[0], code)
        mocks = '''
cc() { local target="${!#}"; printf '#!/bin/sh\nexit 0\n' > "$target"; chmod 755 "$target"; }
pkg-config() { :; }
systemctl() { echo "$*" >> "$MOCK_LOG"; [[ "$*" != "enable lite-dock-splash.service" || "${FAIL_ENABLE:-0}" == 0 ]]; }
sync() { echo "sync $*" >> "$MOCK_LOG"; }
'''
        if os.name == "nt" or sys.platform in ("msys", "cygwin"):
            # NTFS sandbox cannot apply private POSIX ACLs. Exercise the same
            # file operations here; Linux runs the real install/mode handling.
            mocks += '''
install() {
    if [[ "$1" == -d ]]; then
        shift; [[ "$1" != -m ]] || shift 2; mkdir -p "$@"
    else
        [[ "$1" != -m ]] || shift 2; cp "$@"
    fi
}
'''
        (self.root / "tmp").mkdir()
        self.code = mocks + code
        self.env = {"PI_SWITCH_DOCK_RELEASE_LOCKED": "1", "MOCK_LOG": shell_path(self.root / "actions")}

    def installed_hashes(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for folder in ("usr/local", "etc/systemd", "var/lib/lite-dock-splash", "boot/firmware")
                for p in (self.root / folder).rglob("*") if p.is_file()}

    def test_fresh_install_is_permanent_and_repeat_does_not_rewrite_it(self):
        self.prepare()
        result = self.bash(self.code, self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")
        backup = self.root / "var/lib/lite-dock-splash/backup"
        self.assertEqual((backup / "cmdline.txt").read_text(), BASE)
        self.assertEqual((self.root / "boot/firmware/cmdline.txt").read_text(), presentation.prepare_cmdline(BASE))
        unit = self.root / "etc/systemd/system/lite-dock-splash.service"
        self.assertIn("SDL_KMSDRM_DEVICE_INDEX=5", unit.read_text())
        self.assertIn("enable lite-dock-splash.service", (self.root / "actions").read_text())
        # No drop-in-only receiver unit before deploy.sh creates the base unit.
        self.assertFalse((self.root / "etc/systemd/system/switch-frame-tap-viewer.service.d").exists())
        before = self.installed_hashes()
        # A later installer carrying a different build must not even compile.
        result = self.bash(self.code.replace('cc -O2', 'false -O2'), self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")
        self.assertEqual(self.installed_hashes(), before)

    def test_unmanaged_receiver_is_rejected_without_changes(self):
        self.prepare(existing_receiver=True)
        before = self.installed_hashes()
        result = self.bash(self.code, self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("clean installation", result.stderr)
        self.assertEqual(self.installed_hashes(), before)
        self.assertFalse((self.root / "actions").exists())

    def test_enable_failure_restores_boot_and_removes_new_files(self):
        self.prepare()
        config = (self.root / "boot/firmware/config.txt").read_bytes()
        result = self.bash(self.code, {**self.env, "FAIL_ENABLE": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("boot files restored", result.stderr)
        self.assertEqual((self.root / "boot/firmware/cmdline.txt").read_text(), BASE)
        self.assertEqual((self.root / "boot/firmware/config.txt").read_bytes(), config)
        for name in ("usr/local/libexec/lite-dock-splash", "usr/local/share/lite-dock-splash",
                     "etc/systemd/system/lite-dock-splash.service", "var/lib/lite-dock-splash/installed"):
            self.assertFalse((self.root / name).exists())

    def test_boot_preflight_failure_leaves_installation_untouched(self):
        self.prepare()
        (self.root / "boot/firmware/cmdline.txt").write_text(BASE.strip() + " init=/bin/sh\n")
        result = self.bash(self.code, self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "var/lib/lite-dock-splash").exists())
        self.assertFalse((self.root / "actions").exists())

    def test_only_setup_installs_splash(self):
        self.assertIn('bash "$BUNDLE/install-splash.sh"', (ROOT / "setup.sh").read_text())
        for name in ("deploy.sh", "rollback.sh"):
            code = (ROOT / name).read_text()
            self.assertNotIn("install-splash.sh", code)
            self.assertNotIn("boot-presentation.py", code)
            self.assertNotIn("/usr/local/share/lite-dock-splash", code)


if __name__ == "__main__":
    unittest.main()
