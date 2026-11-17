# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the shipped disconnect cleanup with a simulated DRM plane."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


class ScanoutLifecycleTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cc") and shutil.which("patch"), "C compiler and patch required")
    def test_disconnect_releases_overlay_before_waiting(self):
        patches = Path(__file__).resolve().parents[1] / "patches"
        patch = (patches / "low-latency-display.patch").read_text()
        section = patch.split("+++ b/tools/raw-recv/pi-kms-scanout.h\n", 1)[1].split("\n--- ", 1)[0]
        header = "".join(line[1:] for line in section.splitlines(keepends=True)
                         if line.startswith("+") and not line.startswith("+++"))
        # Use the actual display-loop disconnect hunk, not the separate replay
        # loop (which never owns a direct scanout plane).
        disconnect = next(hunk for hunk in re.split(r"(?m)^@@[^\n]*\n", patch)
                          if "         if (g_lost) {\n" in hunk)
        after = "".join(line[1:] for line in disconnect.splitlines(keepends=True)
                        if line.startswith((" ", "+")))
        cleanup = after.split("if (g_lost) {", 1)[1].split("const int never_streamed", 1)[0]
        with tempfile.TemporaryDirectory(prefix="dock-scanout-") as tmp:
            root = Path(tmp)
            target = root / "tools/raw-recv/pi-kms-scanout.h"
            target.parent.mkdir(parents=True)
            target.write_text(header)
            pacing = (patches / "frame-pacing.patch").read_text()
            section = pacing.split("--- a/tools/raw-recv/pi-kms-scanout.h\n", 1)[1].split("--- a/", 1)[0]
            subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-d", str(root)],
                           input="--- a/tools/raw-recv/pi-kms-scanout.h\n" + section,
                           text=True, check=True, capture_output=True)
            actual = target.read_text()
            state = actual[actual.index("typedef struct"):actual.index("static int pi_scan_pacing_active")]
            release = actual[actual.index("static void pi_scan_release"):actual.index("static int pi_scan_init")]
            program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef struct { int id; } AVFrame;
static int fail_disable, disables, releases, frees;
static int drmModeSetPlane(int fd, uint32_t plane, uint32_t crtc,
                          uint32_t fb, uint32_t flags, int32_t x, int32_t y,
                          uint32_t w, uint32_t h, uint32_t sx, uint32_t sy,
                          uint32_t sw, uint32_t sh) {
    (void)flags; (void)x; (void)y; (void)w; (void)h;
    (void)sx; (void)sy; (void)sw; (void)sh;
    assert(fd == 7 && plane == 127 && crtc == 114 && fb == 0);
    assert(releases == 0 && frees == 0); /* disable before releasing buffers */
    disables++;
    if (fail_disable) { errno = EBUSY; return -1; }
    return 0;
}
static int drmModeRmFB(int fd, uint32_t fb) {
    assert(fd == 7 && fb != 0); releases++; return 0;
}
static void av_frame_free(AVFrame **frame) {
    if (*frame) frees++;
    *frame = NULL;
}
'''
            program += state + release
            program += "static void disconnect_cleanup(void) {\n" + cleanup + "\n}\n"
            program += r'''
static AVFrame frames[8];
static void start_stream(void) {
    pi_scan.fd=7; pi_scan.plane=127; pi_scan.crtc=114;
    pi_scan.active=1; pi_scan.current=7; pi_scan.pacing_valid=1;
    disables=releases=frees=0;
    for (int i=0; i<8; i++) {
        pi_scan.frames[i].fb=i+1; pi_scan.frames[i].frame=&frames[i];
    }
}
int main(void) {
    start_stream();
    disconnect_cleanup();
    /* The waiting UI and a subsequent connection must inherit no old plane. */
    assert(disables==1 && releases==8 && frees==8);
    assert(!pi_scan.active && pi_scan.current==-1 && !pi_scan.pacing_valid);
    disconnect_cleanup(); /* repeated cleanup is safe */
    assert(disables==1 && releases==8 && frees==8);
    start_stream(); /* reconnect and disconnect a second time */
    disconnect_cleanup();
    assert(disables==1 && releases==8 && frees==8 && !pi_scan.active);
    start_stream(); fail_disable=1;
    disconnect_cleanup();
    assert(pi_scan.active && releases==0 && frees==0); /* still scanned out */
    fail_disable=0;
    disconnect_cleanup();
    assert(disables==2 && releases==8 && frees==8 && !pi_scan.active);
    return 0;
}
'''
            source = root / "test.c"
            source.write_text(program)
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(source),
                            "-o", str(root / "test")], check=True, capture_output=True)
            subprocess.run([str(root / "test")], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
