# SPDX-License-Identifier: GPL-2.0-only
"""Prepare Pi 4 boot settings conservatively; print 1 if a reboot is needed."""
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import sys


REQUIRED = ("dtoverlay=vc4-kms-v3d", "dtoverlay=dwc2,dr_mode=host")
MODEL_FILTERS = {
    "pi0", "pi0w", "pi02", "pi1", "pi2", "pi3", "pi3+", "pi4", "pi5",
    "pi400", "pi500", "cm0", "cm1", "cm3", "cm3+", "cm4", "cm4s", "cm5",
}


def prepare(text):
    """Return new text, refusing ambiguous or conflicting configurations."""
    model = "pi4"
    conditional = False
    found = set()
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if re.match(r"include\s", line):
            raise ValueError("Review included boot configuration manually before installing.")
        section = re.fullmatch(r"\[([^]]+)\]", line)
        if section:
            name = section[1]
            if name == "all":
                model, conditional = "pi4", False
            elif name in MODEL_FILTERS:
                model = name
            else:
                # Different filter types accumulate until [all]. Do not guess
                # EDID, GPIO, serial, [none], or boot-variable conditions.
                conditional = True
            continue
        if model != "pi4":
            continue
        setting = re.sub(r"\s+", "", line)
        relevant = setting.startswith(("dtoverlay=vc4-", "dtoverlay=dwc2",
                                       "dtoverlay=dwc-otg", "otg_mode="))
        if not relevant:
            continue
        if conditional:
            raise ValueError(f"Review conditional display/USB setting at line {number} manually.")
        if setting.startswith("dtoverlay=vc4-kms-v3d"):
            if setting.split(",", 1)[0] != REQUIRED[0]:
                raise ValueError(f"Unsupported display overlay at line {number}.")
            if "noaudio" in setting.split(",")[1:]:
                raise ValueError(f"HDMI audio is disabled at line {number}; resolve it manually.")
            key = REQUIRED[0]
        elif setting == REQUIRED[1]:
            key = REQUIRED[1]
        else:
            raise ValueError(f"Conflicting display/USB setting at line {number}; resolve it manually.")
        if key in found:
            raise ValueError(f"Duplicate display/USB overlay at line {number}; resolve it manually.")
        found.add(key)
    missing = [item for item in REQUIRED if item not in found]
    if not missing:
        return text
    return text.rstrip("\n") + "\n\n[all]\n# Switch Frame Tap: HDMI KMS and USB-C host\n" + "\n".join(missing) + "\n"


def configure(config, backup_root):
    text = config.read_text(encoding="utf-8")
    updated = prepare(text)
    if updated == text:
        return False
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = backup_root / f"config.txt.before-switch-frame-tap.{stamp}"
    shutil.copy2(config, backup)
    print(f"Boot configuration backup: {backup}", file=sys.stderr)
    config.write_text(updated, encoding="utf-8", newline="\n")
    return True


if __name__ == "__main__":
    try:
        print(int(configure(Path(sys.argv[1]), Path(sys.argv[2]))))
    except (OSError, ValueError) as error:
        sys.exit(str(error))
