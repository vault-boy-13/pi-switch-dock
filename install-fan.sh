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
MODE=install
if [[ "${1:-}" == --update && $# == 1 ]]; then MODE=update
elif (( $# )); then echo "Usage: bash install-fan.sh [--update]" >&2; exit 2; fi

if [[ "$MODE" == update ]] && ! systemctl cat switch-dock-fan.service >/dev/null 2>&1; then
    echo "Fan service is not installed; skipping release fan update."
    exit 0
fi

if [[ "$MODE" == update && ( ! -s "$SCRIPT" || ! -s "$UNIT" ) ]]; then
    echo "Fan service files are incomplete; refusing release fan update." >&2
    exit 1
fi

if [[ "$MODE" == update ]] && cmp -s "$BUNDLE/switch-dock-fan.py" "$SCRIPT" &&
    cmp -s "$BUNDLE/switch-dock-fan.service" "$UNIT"; then
    echo "Fan service already matches this release."
    exit 0
fi

install -d -m 700 "$BACKUP"

for path in "$SCRIPT" "$UNIT"; do
    name="$(basename -- "$path")"
    if [[ -e "$path" ]]; then
        cp -a -- "$path" "$BACKUP/$name"
    else
        printf '%s\n' "$path" >> "$BACKUP/absent-before-install.txt"
    fi
done
ENABLED_BEFORE="$(systemctl is-enabled switch-dock-fan.service 2>/dev/null || true)"
ACTIVE_BEFORE="$(systemctl is-active switch-dock-fan.service 2>/dev/null || true)"
printf '%s\n' "$ENABLED_BEFORE" > "$BACKUP/enabled-before-install.txt"
printf '%s\n' "$ACTIVE_BEFORE" > "$BACKUP/active-before-install.txt"
systemctl cat switch-dock-fan.service > "$BACKUP/unit-before-install.txt" 2>&1 || true
chmod 600 "$BACKUP"/* 2>/dev/null || true

if [[ "$MODE" == update && ( "$ENABLED_BEFORE" != enabled && "$ENABLED_BEFORE" != disabled ) ]]; then
    echo "Fan service has unsupported enablement state: ${ENABLED_BEFORE:-unknown}; refusing release update." >&2
    exit 1
fi

restore_before_state() {
    local path name failed=0
    systemctl stop switch-dock-fan.service >/dev/null 2>&1 || failed=1
    for path in "$SCRIPT" "$UNIT"; do
        name="$(basename -- "$path")"
        if [[ -f "$BACKUP/$name" ]]; then
            cp -a -- "$BACKUP/$name" "$path" || failed=1
        else
            rm -f -- "$path" || failed=1
        fi
    done
    systemctl daemon-reload || failed=1
    if [[ "$ENABLED_BEFORE" == enabled ]]; then
        systemctl enable switch-dock-fan.service || failed=1
    elif [[ "$ENABLED_BEFORE" == disabled ]]; then
        systemctl disable switch-dock-fan.service || failed=1
    fi
    if [[ "$ACTIVE_BEFORE" == active ]]; then
        systemctl start switch-dock-fan.service || failed=1
    else
        systemctl stop switch-dock-fan.service || failed=1
    fi
    return "$failed"
}

restore_on_error() {
    local rc=$?
    trap - ERR
    echo "Fan installation failed; restoring the previous fan service state." >&2
    if ! restore_before_state; then
        echo "Could not fully restore the fan service. Inspect $BACKUP." >&2
    fi
    exit "$rc"
}
trap restore_on_error ERR

if [[ "$ACTIVE_BEFORE" == active ]]; then
    systemctl stop switch-dock-fan.service
fi
install -D -m 755 "$BUNDLE/switch-dock-fan.py" "$SCRIPT"
install -D -m 644 "$BUNDLE/switch-dock-fan.service" "$UNIT"
systemctl daemon-reload
systemctl reset-failed switch-dock-fan.service || true
if [[ "$MODE" == update ]]; then
    if [[ "$ENABLED_BEFORE" == enabled ]]; then
        systemctl enable switch-dock-fan.service
    else
        systemctl disable switch-dock-fan.service
    fi
    if [[ "$ACTIVE_BEFORE" == active ]]; then
        systemctl start switch-dock-fan.service
    fi
else
    systemctl enable --now switch-dock-fan.service
fi
sync -f "$SCRIPT" "$UNIT" "$BACKUP_ROOT"
trap - ERR
if [[ "$MODE" == update ]]; then
    echo "Fan service updated; backup: $BACKUP"
else
    echo "Fan service installed; backup: $BACKUP"
fi
