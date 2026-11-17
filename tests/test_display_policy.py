# SPDX-License-Identifier: GPL-2.0-only
"""Compile and exercise the actual distributed HDMI mode selector."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class DisplayPolicyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cc"), "C compiler required")
    def test_advertised_modes_for_4k_1440p_and_lower_resolution_displays(self):
        patch = (Path(__file__).resolve().parents[1] / "patches/display-policy.patch").read_text()
        section = patch.split("+++ b/tools/raw-recv/pi-display-policy.h\n", 1)[1].split("--- a/", 1)[0]
        header = "".join(line[1:] for line in section.splitlines(keepends=True)
                         if line.startswith("+") and not line.startswith("+++"))
        with tempfile.TemporaryDirectory(prefix="dock-policy-") as tmp:
            root = Path(tmp)
            (root / "pi-display-policy.h").write_text(header)
            (root / "test.c").write_text(r'''
#include <assert.h>
#include <stdlib.h>
#define PI_DISPLAY_POLICY_TEST
#include "pi-display-policy.h"
int main(void) {
    pi_display_mode tv[]={{4096,2160,30},{3840,2160,60},{1920,1080,60},{1920,1080,120}};
    assert(pi_display_pick(tv,4,1)==3);
    assert(pi_display_pick(tv,4,0)==2); /* 120 Hz failed: advertised 60 Hz fallback */
    pi_display_mode qhd[]={{2560,1440,144},{1920,1080,144},{1920,1080,120},{1920,1080,60}};
    assert(pi_display_pick(qhd,4,1)==2); /* select an integer multiple of the 60 fps source */
    pi_display_mode qhd60[]={{2560,1440,60},{1920,1080,60},{1920,1080,30}};
    assert(pi_display_pick(qhd60,3,1)==1);
    pi_display_mode ultra[]={{2560,1080,60},{1920,1080,60}};
    assert(pi_display_pick(ultra,2,1)==1);
    pi_display_mode fhd[]={{1920,1080,60},{1920,1080,120},{1280,720,60}};
    assert(pi_display_pick(fhd,3,1)==-1); /* leave <=1080p displays alone */
    pi_display_mode hd[]={{1280,720,60},{1280,720,50}};
    assert(pi_display_pick(hd,2,1)==-1);
    pi_display_mode missing[]={{3840,2160,30},{1920,1080,30}};
    assert(pi_display_pick(missing,2,1)==-1); /* never invent unsupported modes */
    pi_display_mode fractional[]={{2560,1440,60},{1920,1080,59},{1920,1080,119}};
    assert(pi_display_pick(fractional,3,1)==2);
    assert(pi_display_pick(fractional,3,0)==1);
    assert(pi_display_pick(NULL,0,1)==-1);
    return 0;
}
''')
            result = subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-Werror", "-std=c11",
                                     str(root / "test.c"), "-o", str(root / "test")],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(root / "test")], check=True)

    @unittest.skipUnless(shutil.which("cc"), "C compiler required")
    def test_runtime_mode_failure_falls_back_and_native_override_is_preserved(self):
        patch = (Path(__file__).resolve().parents[1] / "patches/display-policy.patch").read_text()
        section = patch.split("+++ b/tools/raw-recv/pi-display-policy.h\n", 1)[1].split("--- a/", 1)[0]
        header = "".join(line[1:] for line in section.splitlines(keepends=True)
                         if line.startswith("+") and not line.startswith("+++"))
        with tempfile.TemporaryDirectory(prefix="dock-policy-runtime-") as tmp:
            root = Path(tmp)
            (root / "pi-display-policy.h").write_text(header)
            (root / "test.c").write_text(r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { int unused; } SDL_Window;
typedef struct { int w,h,refresh_rate; } SDL_DisplayMode;
#define SDL_WINDOW_FULLSCREEN_DESKTOP 4097
#define SDL_WINDOW_FULLSCREEN 1
static const char *driver="KMSDRM";
static SDL_DisplayMode modes[]={{3840,2160,30},{1920,1080,120},{1920,1080,60}};
static int count=3,fail120,selected_hz,flags,attempts;
static const char *SDL_GetCurrentVideoDriver(void){return driver;}
static int SDL_GetWindowDisplayIndex(SDL_Window *w){(void)w;return 0;}
static int SDL_GetNumDisplayModes(int d){(void)d;return count;}
static int SDL_GetDisplayMode(int d,int i,SDL_DisplayMode *m){(void)d;*m=modes[i];return 0;}
static int SDL_SetWindowDisplayMode(SDL_Window *w,SDL_DisplayMode *m){
    (void)w;attempts++;selected_hz=m->refresh_rate;
    return fail120==1 && selected_hz==120 ? -1:0;
}
static int SDL_SetWindowFullscreen(SDL_Window *w,int f){
    (void)w;flags=f;
    return fail120==2 && selected_hz==120 && f==SDL_WINDOW_FULLSCREEN ? -1:0;
}
static const char *SDL_GetError(void){return "simulated mode failure";}
#include "pi-display-policy.h"
int main(void){
    SDL_Window win={0};unsetenv("SFT_DISPLAY_POLICY");
    assert(pi_display_fullscreen(&win)==0 && selected_hz==120 && flags==1);
    for(fail120=1;fail120<=2;fail120++){
        attempts=0;
        assert(pi_display_fullscreen(&win)==0 && selected_hz==60 && attempts==2);
    }
    fail120=0;attempts=0;setenv("SFT_DISPLAY_POLICY","native",1);
    assert(pi_display_fullscreen(&win)==0 && flags==4097 && attempts==0);
    unsetenv("SFT_DISPLAY_POLICY");driver="x11";
    assert(pi_display_fullscreen(&win)==0 && flags==4097 && attempts==0);
    driver="KMSDRM";count=-1;
    assert(pi_display_fullscreen(&win)==0 && flags==4097 && attempts==0);
    return 0;
}
''')
            result = subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-Werror", "-std=c11",
                                     str(root / "test.c"), "-o", str(root / "test")],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(root / "test")], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
