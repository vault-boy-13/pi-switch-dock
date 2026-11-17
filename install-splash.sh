#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# One-time component, deliberately absent from deploy.sh and rollback.sh.
# stdout is a reboot flag consumed by setup.sh; diagnostics go to stderr.
set -Eeuo pipefail
BUNDLE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ "${PI_SWITCH_DOCK_RELEASE_LOCKED:-}" == 1 && $EUID == 0 ]] || { echo "Use install.sh as root." >&2; exit 1; }
STATE=/var/lib/lite-dock-splash
BINARY=/usr/local/libexec/lite-dock-splash
ASSETS=/usr/local/share/lite-dock-splash
UNIT=/etc/systemd/system/lite-dock-splash.service
CMDLINE=/boot/firmware/cmdline.txt
CONFIG=/boot/firmware/config.txt

if [[ -f "$STATE/installed" ]]; then
    [[ -x "$BINARY" && -d "$ASSETS" && -f "$UNIT" ]] || {
        echo "Permanent splash is incomplete; restore it from $STATE/backup. Receiver updates do not repair it." >&2
        exit 1
    }
    echo "Permanent Lite Dock splash already installed; preserving it." >&2
    echo 0
    exit 0
fi
for path in "$STATE" "$BINARY" "$ASSETS" "$UNIT" /etc/systemd/system/switch-frame-tap-viewer.service; do
    [[ ! -e "$path" && ! -L "$path" ]] || {
        echo "Initial setup requires a clean installation; found $path." >&2; exit 1;
    }
done
# map:1 detaches HDMI fb0 without removing the serial/tty1 consoles. Never map
# to another real framebuffer, or disable filesystem checks to suppress text.
[[ ! -e /sys/class/graphics/fb1 ]] || { echo "Multiple framebuffers: review boot presentation manually." >&2; exit 1; }
[[ -f "$CMDLINE" && -f "$CONFIG" ]] || { echo "Pi boot files not found." >&2; exit 1; }

WORK="$(mktemp -d /tmp/lite-dock-splash.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
cc -O2 -Wall -Wextra -Werror $(pkg-config --cflags sdl2) "$BUNDLE/splash/splash.c" \
    $(pkg-config --libs sdl2) -lm -o "$WORK/lite-dock-splash"
# Preflight boot edits on copies before installing anything permanent.
cp -a "$CMDLINE" "$CONFIG" "$WORK/"
python3 "$BUNDLE/splash/boot-presentation.py" "$WORK/cmdline.txt" "$WORK/config.txt"
INDEX=1
CONNECTED=""
for status in /sys/class/drm/card*-HDMI-A-*/status; do
    [[ -r "$status" && "$(cat "$status")" == connected ]] || continue
    if [[ -z "$CONNECTED" || "$status" == */card1-HDMI-A-1/status ]]; then CONNECTED="$status"; fi
done
if [[ -n "$CONNECTED" ]]; then
    CARD="$(basename "$(dirname "$CONNECTED")")"
    CARD="${CARD%%-*}"; INDEX="${CARD#card}"
fi
sed "s/SDL_KMSDRM_DEVICE_INDEX=1/SDL_KMSDRM_DEVICE_INDEX=$INDEX/" \
    "$BUNDLE/splash/lite-dock-splash.service" > "$WORK/lite-dock-splash.service"

install -d -m 700 "$STATE/backup"
cp -a "$CMDLINE" "$CONFIG" "$STATE/backup/"
rollback_splash() {
    local result=$?
    trap - ERR
    set +e
    systemctl disable --now lite-dock-splash.service >&2
    cp -a "$STATE/backup/cmdline.txt" "$CMDLINE"
    cp -a "$STATE/backup/config.txt" "$CONFIG"
    rm -f -- "$BINARY" "$UNIT" "$STATE/installed"
    rm -rf -- "$ASSETS"
    systemctl daemon-reload >&2
    sync -f /boot/firmware /etc/systemd/system /usr/local "$STATE"
    echo "Splash installation failed; boot files restored. Backup: $STATE/backup" >&2
    exit "$result"
}
trap rollback_splash ERR
install -d -m 755 /usr/local/libexec "$ASSETS"
install -m 755 "$WORK/lite-dock-splash" "$BINARY"
install -m 644 "$BUNDLE"/splash/*.bmp "$ASSETS/"
install -m 644 "$WORK/lite-dock-splash.service" "$UNIT"
# The current receiver unit provides the splash handoff directly.
cp "$WORK/cmdline.txt" "$CMDLINE"
cp "$WORK/config.txt" "$CONFIG"
systemctl daemon-reload >&2
systemctl enable lite-dock-splash.service >&2
sha256sum "$BINARY" "$ASSETS"/*.bmp "$UNIT" > "$STATE/installed"
sync -f /boot/firmware /etc/systemd/system /usr/local "$STATE"
trap - ERR
echo "Permanent English Lite Dock splash installed. Boot backups: $STATE/backup" >&2
echo 1
