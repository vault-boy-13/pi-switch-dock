# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import release_client as client


def metadata(tag="v0.7.19"):
    prefix = f"https://github.com/{client.REPOSITORY}/releases/download/{tag}/"
    return {"tag_name": tag, "draft": False, "prerelease": False,
            "assets": [{"name": name, "browser_download_url": prefix + name}
                       for name in (client.ASSET, "SHA256SUMS")]}


class ReleasesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_missing_manifest_is_only_allowed_for_a_fresh_installation(self):
        current = self.root / 'current/.pi-release.json'
        with patch.object(client, 'CURRENT', current):
            self.assertIsNone(client.installed_version())
            current.parent.mkdir()
            with self.assertRaisesRegex(ValueError, 'clean installation'):
                client.installed_version()

    def bundle(self, extra=None, corrupt=False, target=client.TARGET):
        files = {name: b"file" for name in client.REQUIRED}
        manifest = {"schema": 1, "version": "v0.7.19", "upstream_tag": "v0.7.19", "upstream_sha256": "a" * 64, "target": target,
                    "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        if corrupt:
            files["deploy.sh"] = b"modified"
        files["release.json"] = json.dumps(manifest).encode()
        if extra:
            files.update(extra)
        bundle = self.root / "bundle.tar.gz"
        with tarfile.open(bundle, "w:gz") as archive:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return bundle

    def test_only_our_stable_releases_are_queried(self):
        with patch.object(client, "fetch", return_value=json.dumps(metadata()).encode()) as fetch:
            release, _ = client.find_release()
        self.assertEqual(release["tag_name"], "v0.7.19")
        self.assertEqual(fetch.call_args.args[0], client.API + "/latest")
        self.assertNotIn("TomasUribe", fetch.call_args.args[0])

    def test_release_version_comparison(self):
        self.assertTrue(client.newer("v0.7.20", "v0.7.19"))
        self.assertFalse(client.newer("v0.7.19", "v0.7.19"))
        self.assertFalse(client.newer("v0.7.29", "v0.7.30"))
        self.assertTrue(client.newer("v0.7.19", None))

    def test_draft_prerelease_incomplete_or_foreign_assets_are_rejected(self):
        for kind in ("draft", "prerelease", "missing", "foreign"):
            value = metadata()
            if kind in ("draft", "prerelease"):
                value[kind] = True
            elif kind == "missing":
                value["assets"].pop()
            else:
                value["assets"][0]["browser_download_url"] = "https://example.test/bundle"
            with self.subTest(kind=kind), patch.object(client, "fetch", return_value=json.dumps(value).encode()):
                with self.assertRaises(ValueError):
                    client.find_release()

    def test_no_published_release_does_not_fall_back_to_upstream(self):
        error = client.urllib.error.HTTPError(client.API, 404, "missing", {}, None)
        with patch.object(client, "fetch", side_effect=error) as fetch:
            with self.assertRaisesRegex(ValueError, "No published pi-switch-dock"):
                client.find_release()
        self.assertEqual(fetch.call_count, 1)

    def test_valid_bundle_contains_only_our_tools_and_patches(self):
        manifest = client.unpack(self.bundle(), self.root / "out", "v0.7.19")
        self.assertEqual(manifest["upstream_tag"], "v0.7.19")
        self.assertFalse((self.root / "out/source").exists())
        self.assertFalse((self.root / "out/bin").exists())

    def test_corruption_wrong_version_and_target_rejected_before_extraction(self):
        for kwargs, tag in (({"corrupt": True}, "v0.7.19"), ({}, "v0.7.20"), ({"target": "x86_64"}, "v0.7.19")):
            with self.subTest(kwargs=kwargs, tag=tag):
                out = self.root / "out"
                with self.assertRaises(ValueError):
                    client.unpack(self.bundle(**kwargs), out, tag)
                self.assertFalse(out.exists())

    def test_path_escape_and_unlisted_payload_cannot_be_extracted(self):
        for name in ("../escaped", "/absolute", "source/../../escaped", "unlisted.sh"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    client.unpack(self.bundle({name: b"bad"}), self.root / "out", "v0.7.19")
                self.assertFalse((self.root / "out").exists())

    def test_links_and_duplicate_paths_are_rejected(self):
        for kind in ("link", "duplicate"):
            bundle = self.bundle()
            # Repack with an extra malicious entry.
            with tarfile.open(bundle) as archive:
                entries = [(m, archive.extractfile(m).read()) for m in archive.getmembers()]
            with tarfile.open(bundle, "w:gz") as archive:
                for member, data in entries:
                    archive.addfile(member, io.BytesIO(data))
                member = tarfile.TarInfo("link" if kind == "link" else "deploy.sh")
                if kind == "link":
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/etc"
                archive.addfile(member)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                client.unpack(bundle, self.root / "out", "v0.7.19")

    def test_bad_download_checksum_never_executes_or_unpacks(self):
        release = metadata()
        assets = {a["name"]: a for a in release["assets"]}
        with patch.object(client, "fetch", side_effect=[b"0" * 64 + b"  " + client.ASSET.encode() + b"\n", b"bad"]):
            with self.assertRaisesRegex(ValueError, "bundle checksum mismatch"):
                client.download(assets, self.root, "v0.7.19")
        self.assertFalse((self.root / "payload").exists())

    def test_check_is_read_only_and_uses_project_version(self):
        with patch.object(sys, "argv", ["client", "update", "--check"]), \
             patch.object(client, "find_release", return_value=(metadata("v0.7.20"), {})), \
             patch.object(client, "installed_version", return_value="v0.7.19"), \
             patch.object(client, "download") as download, patch.object(client.subprocess, "run") as run:
            client.main()
        download.assert_not_called()
        run.assert_not_called()

    @unittest.skipIf(os.name == "nt", "Linux maintenance lock")
    def test_same_release_does_not_download_or_restart(self):
        lock = self.root / "lock"
        real_open = open
        def redirected(path, *args, **kwargs):
            return real_open(lock if path == "/run/lock/pi-switch-dock-update.lock" else path, *args, **kwargs)
        with patch.object(sys, "argv", ["client", "update"]), \
             patch.object(client.os, "geteuid", return_value=0), \
             patch("builtins.open", side_effect=redirected), \
             patch.object(client, "find_release", return_value=(metadata(), {})), \
             patch.object(client, "installed_version", return_value="v0.7.19"), \
             patch.object(client, "download") as download, patch.object(client.subprocess, "run") as run:
            client.main()
        download.assert_not_called()
        run.assert_not_called()

    @unittest.skipIf(os.name == "nt", "Linux maintenance lock")
    def test_next_release_uses_receiver_deployment_without_splash_setup(self):
        lock = self.root / "lock"
        payload = self.root / "payload"
        real_open = open

        def redirected(path, *args, **kwargs):
            return real_open(lock if path == "/run/lock/pi-switch-dock-update.lock" else path, *args, **kwargs)

        with patch.object(sys, "argv", ["client", "update"]), \
             patch.object(client.os, "geteuid", return_value=0), \
             patch("builtins.open", side_effect=redirected), \
             patch.object(client, "find_release", return_value=(metadata("v0.7.21"), {})), \
             patch.object(client, "installed_version", return_value="v0.7.20"), \
             patch.object(client, "download", return_value=payload) as download, \
             patch.object(client.subprocess, "run") as run:
            client.main()
        self.assertEqual(download.call_args.args[2], "v0.7.21")
        self.assertEqual(run.call_args.args[0], ["bash", str(payload / "deploy.sh")])
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(run.call_args.kwargs["env"]["PI_SWITCH_DOCK_RELEASE_LOCKED"], "1")


if __name__ == "__main__":
    unittest.main()
