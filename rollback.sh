#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail

DROPIN="/etc/systemd/system/switch-frame-tap-viewer.service.d/zzzz-v4l2-candidate.conf"
SERVICE="switch-frame-tap-viewer.service"
SOURCE_LINK="/opt/pi-switch-dock/current"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PREFERENCES_HELPER="$SCRIPT_DIR/viewer-config.sh"
[[ -s "$PREFERENCES_HELPER" ]] || { echo "Viewer preferences helper missing; reinstall the project release." >&2; exit 1; }
. "$PREFERENCES_HELPER"

if [[ ${EUID} -ne 0 ]]; then
    echo "Run as root (for example: sudo pi-switch-dock-rollback)." >&2
    exit 1
fi
if [[ $# -gt 1 ]]; then
    echo "Usage: $0 [latest|/root/pi-switch-dock/backups/<archive>.tar.gz]" >&2
    exit 2
fi
exec 9>/run/lock/pi-switch-dock-update.lock
flock -n 9 || { echo "Another receiver update or rollback is running." >&2; exit 1; }
if [[ -z "${1:-}" || "$1" == latest ]]; then
    ARCHIVE=""
    if [[ -d /root/pi-switch-dock/backups ]]; then
        ARCHIVE="$(find /root/pi-switch-dock/backups -maxdepth 1 -type f -name '*.tar.gz' -printf '%T@ %p\n' \
            | sort -nr | sed -n '1s/^[^ ]* //p')"
    fi
    [[ -n "$ARCHIVE" ]] || { echo "No rollback archives found." >&2; exit 1; }
else
    [[ -f "$1" ]] || { echo "Rollback archive not found: $1" >&2; exit 1; }
    ARCHIVE="$(readlink -f "$1")"
fi
WORK="$(mktemp -d /tmp/pi-switch-dock-rollback.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
tar -xzf "$ARCHIVE" -C "$WORK"
TOP="$(tar -tzf "$ARCHIVE" | sed -n '1{s,/.*,,;p;}')"
B="${WORK:?}/$TOP"
[[ -s "$B/format" && "$(cat "$B/format")" == pi-switch-dock-rollback-v1 && -s "$B/SHA256SUMS" && -s "$B/release-metadata.tar.gz" && -s "$B/active-release" && -s "$B/viewer-preferences/format" ]] || {
    echo "Incomplete project rollback archive." >&2; exit 1;
}
(cd "$B" && sha256sum -c SHA256SUMS >/dev/null)
[[ -s "$B/current-custom-viewer" && -s "$B/current-viewer-override.conf" ]] || {
    echo "This archive does not contain a Pi viewer rollback." >&2
    exit 1
}
BIN_PATH="$(cat "$B/active-binary-path")"
SOURCE_PATH="$(cat "$B/active-source-path")"
case "$BIN_PATH" in /usr/local/bin/switch-frame-tap-viewer-*) ;; *) echo "Unsafe viewer path in backup." >&2; exit 1;; esac
case "$SOURCE_PATH" in /opt/pi-switch-dock/builds/*/release) ;; *) echo "Unsafe source path in backup." >&2; exit 1;; esac

# A missing display is not a bad release. Leave the current installation intact
# and explain how to retry instead of switching into the same KMSDRM failure.
ENVIRONMENT="$(systemctl show -p Environment --value "$SERVICE")"
DRM_INDEX=""
if [[ "$ENVIRONMENT" =~ SDL_KMSDRM_DEVICE_INDEX=([0-9]+) ]]; then DRM_INDEX="${BASH_REMATCH[1]}"; fi
HDMI_READY=0
for status in /sys/class/drm/card${DRM_INDEX:-*}-HDMI-A-*/status; do
    [[ -r "$status" ]] || continue
    if [[ "$(cat "$status")" == connected ]]; then HDMI_READY=1; break; fi
done
(( HDMI_READY )) || { echo "Connect/turn on the configured HDMI display and retry. Receiver files were not changed." >&2; exit 1; }

cp -a "$DROPIN" "$WORK/previous-dropin"
PREVIOUS_SOURCE="$(readlink -f "$SOURCE_LINK")"
if [[ -f /var/lib/pi-switch-dock/release ]]; then cp -a /var/lib/pi-switch-dock/release "$WORK/previous-release"; fi
save_viewer_preferences "$WORK/previous-preferences"
rollback_failed() {
    rc=$?
    trap - ERR
    set +e
    systemctl stop "$SERVICE"
    cp -a "$WORK/previous-dropin" "$DROPIN"
    ln -sfn "$PREVIOUS_SOURCE" "$SOURCE_LINK"
    if [[ -f "$WORK/previous-release" ]]; then cp -a "$WORK/previous-release" /var/lib/pi-switch-dock/release; else rm -f /var/lib/pi-switch-dock/release; fi
    restore_viewer_preferences "$WORK/previous-preferences"
    systemctl daemon-reload
    if systemctl restart "$SERVICE"; then
        echo "Rollback failed; previous receiver configuration restored. Check service status and logs." >&2
    else
        echo "Rollback failed; previous configuration restored but the receiver could not restart. Check HDMI and service logs." >&2
    fi
    exit "$rc"
}
trap rollback_failed ERR
systemctl stop "$SERVICE"
# Refresh the saved preferences after the viewer has flushed them on exit.
save_viewer_preferences "$WORK/previous-preferences"

# Atomic replacement also permits retrying an already applied rollback.
install -m 755 "$B/current-custom-viewer" "$BIN_PATH.rollback-new"
mv -f -- "$BIN_PATH.rollback-new" "$BIN_PATH"
mkdir -p "$(dirname "$SOURCE_PATH")"
tar -xzf "$B/release-metadata.tar.gz" -C "$(dirname "$SOURCE_PATH")"
[[ -s "$SOURCE_PATH/.pi-release.json" ]] || { echo "Release manifest missing from saved source." >&2; false; }
install -m 644 "$B/current-viewer-override.conf" "$DROPIN"
restore_viewer_preferences "$B/viewer-preferences"
install -m 644 "$B/active-release" /var/lib/pi-switch-dock/release
ln -sfn "$SOURCE_PATH" "$SOURCE_LINK"
systemctl daemon-reload
systemctl restart "$SERVICE"
LAST_PID=""
STABLE=0
for ((attempt=0; attempt<30; attempt++)); do
    PID="$(systemctl show --property=MainPID --value "$SERVICE")"
    RUNNING_BIN="$(readlink -f "/proc/$PID/exe" 2>/dev/null)" || RUNNING_BIN=""
    if systemctl is-active --quiet "$SERVICE" && [[ "$RUNNING_BIN" == "$BIN_PATH" ]]; then
        if [[ "$PID" == "$LAST_PID" ]]; then STABLE=$((STABLE + 1)); else STABLE=1; fi
        if (( STABLE >= 10 )); then break; fi
    else STABLE=0; fi
    LAST_PID="$PID"
    sleep 1
done
if (( STABLE < 10 )); then
    journalctl -u "$SERVICE" -n 12 --no-pager >&2 || true
    false # Invoke recovery through ERR, rather than bypassing it with exit.
fi
trap - ERR
echo "Restored viewer: $BIN_PATH"
echo "Restored release metadata: $SOURCE_PATH"
