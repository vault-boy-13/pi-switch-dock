#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail

BUNDLE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ "${PI_SWITCH_DOCK_RELEASE_LOCKED:-}" == 1 ]] || { echo "Use install.sh." >&2; exit 1; }
. "$BUNDLE/tools.sh"
INSTALL_DIR=/opt/pi-switch-dock
RULE=/etc/udev/rules.d/70-switch-frame-tap.rules
CONFIG=/boot/firmware/config.txt
(( $# == 0 )) || { echo "Usage: bash install.sh" >&2; exit 2; }

if (( EUID != 0 )); then
    echo "Run with sudo: sudo bash install.sh" >&2
    exit 1
fi

if [[ ! -r /etc/os-release ]]; then
    echo "Cannot identify the operating system." >&2
    exit 1
fi
. /etc/os-release
if [[ "${ID:-}" != debian && "${ID:-}" != raspbian ]] || [[ "${VERSION_CODENAME:-}" != trixie ]]; then
    echo "Supported system: Raspberry Pi OS Lite 64-bit (Debian Trixie). Found ${PRETTY_NAME:-unknown}." >&2
    exit 1
fi
[[ "$(uname -m)" == aarch64 || "$(uname -m)" == arm64 ]] || {
    echo "A 64-bit Raspberry Pi OS is required; found $(uname -m)." >&2
    exit 1
}

ASSET_DIR="$BUNDLE"

echo "Installing ARM64 build dependencies (no full OS upgrade)."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    build-essential ca-certificates curl python3 pkg-config patch \
    libusb-1.0-0-dev libsdl2-dev libdrm-dev libavcodec-dev libavutil-dev libavformat-dev \
    python3-lgpio v4l-utils

echo "Installing the temperature-controlled GPIO18 fan service."
bash "$BUNDLE/install-fan.sh"

echo "Enabling the Lite Dock HDMI-CEC name."
bash "$BUNDLE/install-cec.sh"

if [[ ! -f "$CONFIG" ]]; then
    echo "Boot configuration not found: $CONFIG" >&2
    exit 1
fi
CONFIG_CHANGED="$(python3 "$ASSET_DIR/boot_config.py" "$CONFIG" /root)"
SPLASH_CHANGED="$(bash "$BUNDLE/install-splash.sh")"
if (( CONFIG_CHANGED || SPLASH_CHANGED )); then
    install -d -m 755 "$INSTALL_DIR"
    cat /proc/sys/kernel/random/boot_id > "$INSTALL_DIR/reboot-required"
fi

activate_tools "$BUNDLE"


if [[ -e "$RULE" ]]; then
    cp -a "$RULE" "/root/70-switch-frame-tap.rules.before-install.$(date +%Y%m%d-%H%M%S)"
fi
cat > "$RULE" <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="1209", ATTRS{idProduct}=="5f1e", MODE="0660", TAG+="uaccess"
EOF
udevadm control --reload-rules
udevadm trigger

# Persist tools, backups, USB rules and the boot partition before asking the
# user to reboot or handing off to the updater. Treat write errors as failure.
sync -f "$INSTALL_DIR" /usr/local/sbin /root "$RULE" "$CONFIG"

if [[ -f "$INSTALL_DIR/reboot-required" && "$(cat "$INSTALL_DIR/reboot-required")" == "$(cat /proc/sys/kernel/random/boot_id)" ]]; then
    echo "Boot settings prepared. Run sudo reboot, reconnect over SSH, then run sudo pi-switch-dock-update."
    echo "The receiver has not been installed/updated yet."
    exit 0
fi

echo "Installing the published pi-switch-dock receiver."
bash "$BUNDLE/deploy.sh"

echo "Setup complete. The receiver starts automatically at boot."
echo "Update later with: sudo pi-switch-dock-update"
echo "View logs with:    sudo journalctl -u switch-frame-tap-viewer -f"
