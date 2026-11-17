# SPDX-License-Identifier: GPL-2.0-only
"""Initial boot presentation only. Never called by receiver maintenance."""
from pathlib import Path
import sys

OPTIONS = ("quiet", "loglevel=3", "logo.nologo", "vt.global_cursor_default=0",
           "systemd.show_status=false", "fbcon=map:1")


def prepare_cmdline(text):
    lines = text.strip().splitlines()
    if len(lines) != 1:
        raise ValueError("Expected a single-line kernel command line")
    tokens = lines[0].split()
    if not any(t.startswith("root=") for t in tokens) or "console=tty1" not in tokens:
        raise ValueError("Keep the existing root= and console=tty1 before installing the splash")
    if any(t.startswith(("init=", "rdinit=")) for t in tokens):
        raise ValueError("Recovery boot arguments found; restore normal boot first")
    if any(t.startswith("fbcon=") and t != "fbcon=map:1" for t in tokens):
        raise ValueError("Review existing framebuffer console mapping manually")
    keys = {t.split("=", 1)[0] for t in OPTIONS}
    return " ".join([t for t in tokens if t.split("=", 1)[0] not in keys] + list(OPTIONS)) + "\n"


def prepare_config(text):
    block = "[all]\n# Lite Dock permanent boot presentation\ndisable_splash=1\n"
    if text.endswith(block):
        return text
    return text.rstrip("\n") + "\n\n" + block


def configure(cmdline, config):
    # Validate both inputs before the first write. Backups/rollback belong to
    # install-splash.sh; never alter root, consoles, networking or initramfs.
    command = prepare_cmdline(cmdline.read_text())
    firmware = prepare_config(config.read_text())
    cmdline.write_text(command, encoding="utf-8", newline="\n")
    config.write_text(firmware, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    try:
        configure(Path(sys.argv[1]), Path(sys.argv[2]))
    except (ValueError, OSError) as error:
        sys.exit(str(error))
