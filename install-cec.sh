#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail

BUNDLE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
(( EUID == 0 )) || { echo "Run as root." >&2; exit 1; }
SCRIPT=/usr/local/sbin/lite-dock-cec-name.py
UNIT=/etc/systemd/system/lite-dock-cec-name.service
MODE=install
if [[ "${1:-}" == --update && $# == 1 ]]; then MODE=update
elif (( $# )); then echo "Usage: bash install-cec.sh [--update]" >&2; exit 2; fi

if ! command -v cec-ctl >/dev/null; then
    echo "Installing v4l-utils for HDMI-CEC support."
    DEBIAN_FRONTEND=noninteractive apt-get install -y v4l-utils
fi

EXISTING=0
if systemctl cat lite-dock-cec-name.service >/dev/null 2>&1; then EXISTING=1; fi
if [[ "$MODE" == update && "$EXISTING" == 1 ]] &&
    cmp -s "$BUNDLE/lite-dock-cec-name.py" "$SCRIPT" &&
    cmp -s "$BUNDLE/lite-dock-cec-name.service" "$UNIT"; then
    echo "HDMI-CEC name service already matches this release."
    exit 0
fi

install -D -m 755 "$BUNDLE/lite-dock-cec-name.py" "$SCRIPT"
install -D -m 644 "$BUNDLE/lite-dock-cec-name.service" "$UNIT"
systemctl daemon-reload
if [[ "$EXISTING" == 0 ]]; then
    systemctl enable lite-dock-cec-name.service
fi
sync -f "$SCRIPT" "$UNIT" /etc/systemd/system
echo "HDMI-CEC name service installed; it will configure the name at next boot."
