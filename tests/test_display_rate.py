# SPDX-License-Identifier: GPL-2.0-only
"""Compile the selector carried by the distributed patch, not a copied model."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class DisplayRateTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cc"), "C compiler required")
    def test_native_scanout_is_not_gated_by_frame_rate(self):
        patch = (Path(__file__).resolve().parents[1] / "patches/low-latency-display.patch").read_text()
        section = patch.split("+++ b/tools/raw-recv/raw-view.c\n", 1)[1].split("\n--- ", 1)[0]
        added = "\n".join(line[1:] for line in section.splitlines()
                          if line.startswith("+") and not line.startswith("+++"))
        start = added.index("static int pi_native_display")
        native_display = added[start:added.index("\n}", start) + 2]
        with tempfile.TemporaryDirectory(prefix="dock-native-display-") as tmp:
            root = Path(tmp)
            source = root / "test.c"
            source.write_text(r'''
#include <assert.h>
static int scanout_enabled=1;
static int pi_scan_enabled(void) { return scanout_enabled; }
''' + native_display + r'''
int main(void) {
    assert(pi_native_display(1920,1080));
    assert(!pi_native_display(1280,720));
    scanout_enabled=0;
    assert(!pi_native_display(1920,1080));
    return 0;
}
''')
            subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-Werror", str(source),
                            "-o", str(root / "test")], check=True, capture_output=True)
            subprocess.run([str(root / "test")], check=True)

    @unittest.skipUnless(shutil.which("cc"), "C compiler required")
    def test_protected_modes_and_transitions(self):
        patch = (Path(__file__).resolve().parents[1] / "patches/low-latency-display.patch").read_text()
        section = patch.split("+++ b/tools/raw-recv/pi-display-rate.h\n", 1)[1].split("\n--- ", 1)[0]
        header = "".join(line[1:] for line in section.splitlines(keepends=True)
                         if line.startswith("+") and not line.startswith("+++"))
        with tempfile.TemporaryDirectory(prefix="dock-display-") as tmp:
            root = Path(tmp)
            actual = root / "tools/raw-recv/pi-display-rate.h"
            actual.parent.mkdir(parents=True)
            actual.write_text(header)
            pacing = (Path(__file__).resolve().parents[1] / "patches/frame-pacing.patch").read_text()
            section = pacing.split("--- a/tools/raw-recv/pi-display-rate.h\n", 1)[1].split("--- a/", 1)[0]
            subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-d", str(root)],
                           input="--- a/tools/raw-recv/pi-display-rate.h\n" + section,
                           text=True, check=True, capture_output=True)
            (root / "pi-display-rate.h").write_text(actual.read_text())
            (root / "test.c").write_text(r'''
#include <assert.h>
#include "pi-display-rate.h"
int main(void) {
    pi_display_rate s = {0}; int mode = 0;
    for (uint32_t i=0; i<600; i++)
        assert(!pi_display_rate_sample(&s,i,1920,1080,i*1000000ULL/30,1000000));
    s=(pi_display_rate){0};
    for (uint32_t i=0; i<600; i++)
        assert(!pi_display_rate_sample(&s,i,1280,720,i*1000000ULL/60,1000000));
    s=(pi_display_rate){0};
    for (uint32_t i=0; i<180; i++)
        mode=pi_display_rate_sample(&s,i,1920,1080,i*1000000ULL/60,1000000);
    assert(mode && s.pace60);
    /* Session change must protect a newly started 30fps game. */
    assert(!pi_display_rate_sample(&s,0,1920,1080,3000000,1000000));
    for (uint32_t i=1; i<90; i++)
        assert(!pi_display_rate_sample(&s,i,1920,1080,3000000+i*1000000ULL/30,1000000));
    s=(pi_display_rate){0};
    for (uint32_t i=0; i<180; i++)
        mode=pi_display_rate_sample(&s,i,1920,1080,i*1000000ULL/60,1000000);
    assert(mode);
    assert(!pi_display_rate_sample(&s,180,1280,720,3000000,1000000));
    s=(pi_display_rate){0};
    for (uint32_t i=0; i<180; i++)
        mode=pi_display_rate_sample(&s,i,1920,1080,i*1000000ULL/60,1000000);
    assert(mode);
    assert(!pi_display_rate_sample(&s,180,1920,1080,9000000,1000000));
    assert(!s.pace60);
    /* High-rate 50/120 fps streams must not be forced onto a 60 fps clock. */
    for (int fps=50; fps<=120; fps+=70) {
        s=(pi_display_rate){0};
        for (uint32_t i=0; i<600; i++)
            mode=pi_display_rate_sample(&s,i,1920,1080,i*1000000ULL/fps,1000000);
        assert(mode && !s.pace60);
    }
    return 0;
}
''')
            subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-std=c11", str(root / "test.c"),
                            "-o", str(root / "test")], check=True, capture_output=True)
            subprocess.run([str(root / "test")], check=True)


if __name__ == "__main__":
    unittest.main()
