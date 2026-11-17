#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail

BUNDLE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
(( EUID == 0 )) || { echo "Run as root." >&2; exit 1; }
python3 -c 'import lgpio' || {
    echo "python3-lgpio is required; install it before the fan service." >&2
    exit 1
}

SCRIPT=/usr/local/sbin/switch-dock-fan.py
UNIT=/etc/systemd/system/switch-dock-fan.service
BACKUP_ROOT=/root/pi-switch-dock/backups
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$BACKUP_ROOT/fan-$STAMP"
install -d -m 700 "$BACKUP"

for path in "$SCRIPT" "$UNIT"; do
    name="$(basename -- "$path")"
    if [[ -e "$path" ]]; then
        cp -a -- "$path" "$BACKUP/$name"
    else
        printf '%s\n' "$path" >> "$BACKUP/absent-before-install.txt"
    fi
done
systemctl is-enabled switch-dock-fan.service > "$BACKUP/enabled-before-install.txt" 2>&1 || true
systemctl is-active switch-dock-fan.service > "$BACKUP/active-before-install.txt" 2>&1 || true
systemctl cat switch-dock-fan.service > "$BACKUP/unit-before-install.txt" 2>&1 || true
chmod 600 "$BACKUP"/* 2>/dev/null || true

if systemctl is-active --quiet switch-dock-fan.service; then
    systemctl stop switch-dock-fan.service
fi
install -D -m 755 "$BUNDLE/switch-dock-fan.py" "$SCRIPT"
install -D -m 644 "$BUNDLE/switch-dock-fan.service" "$UNIT"
systemctl daemon-reload
systemctl reset-failed switch-dock-fan.service || true
systemctl enable --now switch-dock-fan.service
sync -f "$SCRIPT" "$UNIT" "$BACKUP_ROOT"
echo "Fan service installed; backup: $BACKUP"
