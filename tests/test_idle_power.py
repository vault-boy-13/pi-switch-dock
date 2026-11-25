# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the policy shipped in the patch; hardware tests are explicitly opt-in."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class IdlePowerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'C compiler required')
    def test_actual_policy_boundaries_media_and_long_idle(self):
        patch = (ROOT / 'patches/idle-power.patch').read_text()
        section = patch.split('+++ b/tools/raw-recv/pi-idle-policy.h\n', 1)[1]
        header = ''.join(line[1:] for line in section.splitlines(keepends=True)
                         if line.startswith('+') and not line.startswith('+++'))
        with tempfile.TemporaryDirectory(prefix='dock-idle-policy-') as tmp:
            work = Path(tmp)
            (work / 'pi-idle-policy.h').write_text(header)
            result = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                                     '-I', str(work), str(ROOT / 'tests/idle-policy.c'),
                                     '-o', str(work / 'test')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(work / 'test')], check=True, capture_output=True)

    @unittest.skipUnless(os.environ.get('RUN_PI_IDLE_INTEGRATION') == '1',
                         'opt-in Pi hardware test; requires an isolated patched source tree')
    def test_actual_reader_and_v4l2_audio_lifecycle(self):
        source = Path(os.environ['PI_IDLE_TEST_SOURCE']).resolve()
        self.assertTrue(source.is_file())
        # The test uses dummy SDL video/audio and the real V4L2 decoder, never USB.
        flags = shlex.split(subprocess.check_output([
            'pkg-config', '--cflags', '--libs', 'libusb-1.0', 'sdl2',
            'libavcodec', 'libavutil', 'libavformat', 'libdrm'], text=True))
        with tempfile.TemporaryDirectory(prefix='dock-idle-lifecycle-') as tmp:
            binary = Path(tmp) / 'test'
            result = subprocess.run([
                'cc', '-O1', '-DSFT_H264', '-DSFT_MP4',
                '-DSFT_VERSION="idle-lifecycle-test"',
                f'-DSFT_TEST_VIEWER_SOURCE="{source}"',
                str(ROOT / 'tests/idle-lifecycle.c'), '-o', str(binary),
                *flags, '-lm'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('20 V4L2/audio release/resume cycles', result.stdout)
            self.assertIn('reader: status, stale/truncated media', result.stdout)


if __name__ == '__main__':
    unittest.main()
