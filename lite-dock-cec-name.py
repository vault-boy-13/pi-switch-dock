#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Advertise the Lite Dock name through HDMI-CEC."""
import logging
from pathlib import Path
import subprocess

CEC_DIRECTORY = Path("/dev")
OSD_NAME = "Lite Dock"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lite-dock-cec-name")


def configure_adapters(device_directory=CEC_DIRECTORY, run=None):
    if run is None:
        run = subprocess.run
    adapters = sorted(device_directory.glob("cec*"))
    if not adapters:
        log.warning("No HDMI-CEC adapters found; skipping device name setup")
        return

    configured = 0
    failed = []
    for adapter in adapters:
        try:
            run(["/usr/bin/cec-ctl", "--device", str(adapter),
                 "--playback", "--osd-name", OSD_NAME], check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            log.error("Could not configure HDMI-CEC adapter %s: %s", adapter, error)
            failed.append(adapter)
        else:
            configured += 1

    if configured == 0:
        raise RuntimeError("Could not configure any HDMI-CEC adapter")
    if failed:
        log.warning("Configured %d HDMI-CEC adapter(s); %d failed", configured, len(failed))
    else:
        log.info("Configured %d HDMI-CEC adapter(s) as %s", configured, OSD_NAME)


if __name__ == "__main__":
    try:
        configure_adapters()
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"lite-dock-cec-name: {error}")
