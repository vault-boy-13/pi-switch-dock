# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import release_client

def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

source_tool = load('prepare-source')
packager = load('package-release')


class SourcePackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def archive(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            for name in ('common/sft_version.h', 'tools/raw-recv/raw-view.c', 'tools/raw-recv/Makefile'):
                member = tarfile.TarInfo('switch-frame-tap-0.7.19/' + name)
                member.size = 4
                archive.addfile(member, io.BytesIO(b'code'))
        return data.getvalue()

    def manifest(self, archive):
        spec = self.root / 'spec.json'
        spec.write_text(json.dumps({'version': 'v0.7.19', 'upstream_tag': 'v0.7.19',
                                   'upstream_sha256': hashlib.sha256(archive).hexdigest()}))
        return spec

    def test_source_download_uses_only_pinned_tag_and_verifies_archive(self):
        data = self.archive()
        with patch.object(source_tool.urllib.request, 'urlopen', return_value=io.BytesIO(data)) as get:
            source_tool.prepare(self.manifest(data), self.root / 'source')
        self.assertEqual(get.call_args.args[0],
                         'https://github.com/TomasUribe/switch-frame-tap/archive/refs/tags/v0.7.19.tar.gz')
        self.assertEqual((self.root / 'source/tools/raw-recv/raw-view.c').read_bytes(), b'code')

    def test_bad_source_checksum_stops_before_unpack(self):
        spec = self.manifest(self.archive())
        with patch.object(source_tool.urllib.request, 'urlopen', return_value=io.BytesIO(b'bad')):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                source_tool.prepare(spec, self.root / 'source')
        self.assertFalse((self.root / 'source').exists())

    def test_package_contains_only_our_files_and_no_author_source_or_binary(self):
        packager.package(self.manifest(self.archive()), self.root / 'dist')
        bundle = self.root / 'dist' / release_client.ASSET
        with tarfile.open(bundle) as archive:
            self.assertEqual(set(archive.getnames()), release_client.REQUIRED | {'release.json'})
            self.assertFalse(any(name.startswith(('source/', 'bin/')) for name in archive.getnames()))

    def test_project_version_must_equal_supported_author_version(self):
        spec = self.manifest(self.archive())
        value = json.loads(spec.read_text())
        value['version'] = 'v0.7.20'
        spec.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'must match upstream'):
            packager.package(spec, self.root / 'dist')

    def test_current_package_applies_disconnect_fix_during_receiver_build(self):
        """Check the actual distributable, including the shared install/update path."""
        packager.package(ROOT / 'release-spec.json', self.root / 'dist')
        spec = json.loads((ROOT / 'release-spec.json').read_text())
        payload = self.root / 'verified'
        manifest = release_client.unpack(self.root / 'dist' / release_client.ASSET,
                                         payload, spec['version'])
        self.assertNotIn('package_revision', manifest)
        self.assertEqual(manifest['version'], 'v0.7.23')
        self.assertEqual(manifest['upstream_tag'], 'v0.7.23')
        deployment = (payload / 'deploy.sh').read_text()
        self.assertIn('Environment=SFT_KMS_SCANOUT=1', deployment)
        self.assertIn('Environment=SFT_SCANOUT_PACING=0', deployment)
        self.assertEqual(deployment.count('Environment=SFT_IDLE_TIMEOUT=600'), 2)
        adaptation = (payload / 'patches/low-latency-display.patch').read_text()
        branch = adaptation.split('         if (g_lost) {\n', 1)[1].split('             reader_stop();', 1)[0]
        self.assertIn('+            pi_scan_hide();', branch)
        self.assertIn('low-latency-display.patch', (payload / 'build-receiver.sh').read_text())
        self.assertIn('idle-power.patch', (payload / 'build-receiver.sh').read_text())
        self.assertIn('idle-power.patch', deployment)
        idle = (payload / 'patches/idle-power.patch').read_text()
        self.assertIn('pi_idle_video_fresh', idle)
        self.assertIn('SDL_Delay(pi_idle.sleeping ? 250 : 50)', idle)
        self.assertIn('build-receiver.sh', (payload / 'deploy.sh').read_text())
        self.assertIn('deploy.sh', (payload / 'setup.sh').read_text())
        self.assertEqual(set(manifest['files']), release_client.REQUIRED)
