#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Start the viewer when HDMI is ready and request TV wake over CEC."""

import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import time

DRM = Path("/sys/class/drm")
USB = Path("/sys/bus/usb/devices")
VIEWER_LOG = Path("/root/.local/state/switch-frame-tap/viewer.log")
VIEWER = "switch-frame-tap-viewer.service"
VIEWER_ENV = Path("/run/lite-dock-viewer-hdmi/output.env")
MEDIA = re.compile(r"^\[\s*[\d.]+ s\] decoded .*?, shown ([\d.]+) fps, .*?\| audio ([\d.]+) KB/s")
MEDIA_GAP = 15
POLL_INTERVAL = 2
log = logging.getLogger("lite-dock-hdmi")


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def hdmi_ready():
    card = os.environ.get("SDL_KMSDRM_DEVICE_INDEX", "*")
    return tuple(p.name for p in sorted(DRM.glob(f"card{card}-HDMI-A-*"))
                 if read(p / "status") == "connected" and (read(p / "modes") or has_edid(p)))


def has_edid(connector):
    # KMS may leave the mode list empty on hotplug until the viewer probes it.
    try:
        with (connector / "edid").open("rb") as stream:
            block = stream.read(128)
    except OSError:
        return False
    return (len(block) == 128 and block.startswith(b"\x00\xff\xff\xff\xff\xff\xff\x00")
            and sum(block) % 256 == 0)


def switch_connected():
    return any(read(p / "idProduct") == "5f1e"
               for p in USB.glob("*") if read(p / "idVendor") == "1209")


def prepare_viewer(connectors):
    # Prefer the enabled output when both ports are connected.
    connector = next((name for name in connectors if read(DRM / name / "enabled") == "enabled"),
                     connectors[0])
    port = int(connector.rsplit("-", 1)[1]) - 1
    sink = f"plughw:CARD=vc4hdmi{port},DEV=0"
    pending = VIEWER_ENV.with_suffix(".new")
    pending.write_text(f"AUDIODEV={sink}\nLITE_DOCK_HDMI_OUTPUT={connector}\n")
    pending.replace(VIEWER_ENV)
    log.info("HDMI output %s, ALSA %s", connector, sink)


def start_viewer(connectors):
    selection = next((line.split("=", 1)[1] for line in read(VIEWER_ENV).splitlines()
                      if line.startswith("LITE_DOCK_HDMI_OUTPUT=")), "")
    action = "restart" if selection and selection not in connectors else "start"
    log.info("HDMI ready on %s; requesting viewer %s", ", ".join(connectors), action)
    subprocess.run(["/usr/bin/systemctl", action, "--no-block", VIEWER], timeout=5, check=True)


class MediaLog:
    """Read only new complete statistics lines from the installed viewer."""

    def __init__(self, path):
        self.path = path
        self.inode = None
        self.offset = 0
        self.media(seek_end=True)

    def media(self, seek_end=False):
        try:
            with self.path.open("rb") as stream:
                stat = os.fstat(stream.fileno())
                inode = (stat.st_dev, stat.st_ino)
                if inode != self.inode or stat.st_size < self.offset:
                    self.inode, self.offset = inode, 0
                if seek_end:
                    self.offset = stat.st_size
                    return False
                if stat.st_size == self.offset:
                    return False
                stream.seek(max(self.offset, stat.st_size - 65536))
                data = stream.read(65536)
                end = data.rfind(b"\n") + 1
                if not end:
                    return False
                self.offset = stream.tell() - len(data) + end
        except OSError:
            return False
        for line in data[:end].decode(errors="replace").splitlines():
            match = MEDIA.match(line)
            if match and any(float(value) > 0 for value in match.groups()):
                return True
        return False


def wake_tv(reason, connectors):
    # vc4 names its adapters by the HDMI port, independently of /dev/cecN.
    ports = sorted({int(name.rsplit("-", 1)[1]) - 1 for name in connectors}) or [0, 1]
    for port in ports:
        try:
            adapter = ["/usr/bin/cec-ctl", "--adapter", f"vc4-hdmi-{port}", "--skip-info"]
            address = subprocess.run(
                adapter + ["--physical-address"], capture_output=True, text=True, timeout=3,
            ).stdout.strip()
            wake = ["--to", "0", "--image-view-on"]
            if re.fullmatch(r"[0-9a-eA-E](?:\.[0-9a-fA-F]){3}", address):
                wake += ["--active-source", f"phys-addr={address}"]
            result = subprocess.run(
                adapter + wake, capture_output=True, text=True, timeout=3,
            )
            detail = " ".join((result.stdout + result.stderr).split())
            log.info("CEC wake (%s), HDMI port %d, exit %d: %s",
                     reason, port + 1, result.returncode, detail or "(no status)")
        except (OSError, subprocess.TimeoutExpired) as error:
            log.info("CEC wake (%s), HDMI port %d: %s", reason, port + 1, error)


def run():
    media = MediaLog(VIEWER_LOG)
    connectors = hdmi_ready()
    last_connectors = connectors
    previous_hdmi = ()
    previous_usb = False
    last_media = None
    usb_wake_pending = False
    wake_tv("dock startup", connectors)
    while True:
        connectors = hdmi_ready()
        connected = switch_connected()
        now = time.monotonic()
        if connectors and connectors != previous_hdmi:
            start_viewer(connectors)
        elif not connectors and previous_hdmi:
            log.info("HDMI unavailable; waiting for a video mode")
        if connectors:
            last_connectors = connectors
        if not connected:
            last_media = None
            usb_wake_pending = False
        elif not previous_usb and not connectors:
            # The viewer cannot confirm media until KMSDRM can start.
            wake_tv("Switch USB connected; waiting for HDMI", connectors)
            usb_wake_pending = True
        if media.media() and connected:
            if not usb_wake_pending and (last_media is None or now - last_media >= MEDIA_GAP):
                wake_tv("Switch media started", last_connectors)
            last_media = now
            usb_wake_pending = False
        previous_hdmi, previous_usb = connectors, connected
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if sys.argv[1:] in (["--hdmi-ready"], ["--prepare-viewer"]):
        connectors = hdmi_ready()
        if not connectors:
            log.info("HDMI unavailable; waiting for a video mode")
            sys.exit(1)
        if sys.argv[1:] == ["--prepare-viewer"]:
            prepare_viewer(connectors)
    elif not sys.argv[1:]:
        run()
    else:
        sys.exit("Usage: lite-dock-hdmi.py [--hdmi-ready | --prepare-viewer]")
