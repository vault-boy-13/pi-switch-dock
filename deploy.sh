#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail

BUNDLE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ "${PI_SWITCH_DOCK_RELEASE_LOCKED:-}" == 1 ]] || { echo "Use pi-switch-dock-update." >&2; exit 1; }
DROPIN="/etc/systemd/system/switch-frame-tap-viewer.service.d/zzzz-v4l2-candidate.conf"
UNIT="/etc/systemd/system/switch-frame-tap-viewer.service"
SERVICE="switch-frame-tap-viewer.service"
BUILD_ROOT="/opt/pi-switch-dock/builds"
BACKUP_ROOT="/root/pi-switch-dock/backups"
SOURCE_LINK="/opt/pi-switch-dock/current"
STATE_DIR="/var/lib/pi-switch-dock"
STATE_FILE="$STATE_DIR/release"
BIN_ROOT="/usr/local/bin"

# syncfs (GNU sync -f) waits for data AND directory metadata and reports I/O
# errors. Flush each destination filesystem, including separate /opt or /root.
persist_installation() {
    sync -f "$BIN_ROOT" "$BUILD_ROOT" /etc/systemd/system "$STATE_DIR" /opt/pi-switch-dock
    if [[ -d "$BACKUP_ROOT" ]]; then sync -f "$BACKUP_ROOT"; fi
}

# Prune only timestamped artifacts created by this updater. Keep the current
# installation and its immediate predecessor; the archive is the rollback copy.
prune_previous_versions() {
    local entry name resolved verify top previous_bin previous_source
    local -a entries
    for entry in "$BUILD_ROOT" "$BACKUP_ROOT" "$BIN_ROOT"; do
        [[ -d "$entry" && ! -L "$entry" && "$(readlink -f -- "$entry")" == "$entry" ]] || return 1
    done
    [[ -f "$ROLLBACK_ARCHIVE" && ! -L "$ROLLBACK_ARCHIVE" ]] || return 1
    verify="$(mktemp -d "$WORK/verify.XXXXXX")" || return 1
    tar -xzf "$ROLLBACK_ARCHIVE" -C "$verify" || return 1
    top="$(basename "$ROLLBACK_ARCHIVE" .tar.gz)"
    [[ -s "$verify/$top/SHA256SUMS" ]] || return 1
    (cd "$verify/$top" && sha256sum -c SHA256SUMS >/dev/null) || return 1
    previous_bin="$(cat "$verify/$top/active-binary-path")" || return 1
    previous_source="$(cat "$verify/$top/active-source-path")" || return 1
    shopt -s nullglob
    entries=("$BACKUP_ROOT"/* "$BUILD_ROOT"/* "$BIN_ROOT"/switch-frame-tap-viewer-*)
    shopt -u nullglob
    for entry in "${entries[@]}"; do
        [[ ! -L "$entry" ]] || continue
        name="${entry##*/}"
        resolved="$(readlink -f -- "$entry")" || return 1
        case "$entry" in
            "$BACKUP_ROOT"/*)
                [[ "$name" =~ ^[0-9]{8}-[0-9]{6}-v[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?(\.tar\.gz(\.pending)?)?$ ]] || continue
                [[ "$entry" != "$ROLLBACK_ARCHIVE" ]] || continue
                [[ "$resolved" == "$BACKUP_ROOT/$name" ]] || return 1
                ;;
            "$BUILD_ROOT"/*)
                [[ -d "$entry" && "$name" =~ ^[0-9]{8}-[0-9]{6}-v[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || continue
                [[ "$resolved/release" != "$BUILD_DIR/release" && "$resolved/release" != "$previous_source" ]] || continue
                [[ "$resolved" == "$BUILD_ROOT/$name" ]] || return 1
                ;;
            "$BIN_ROOT"/*)
                [[ -f "$entry" && "$name" =~ ^switch-frame-tap-viewer-v[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?-v4l2-[0-9]{8}-[0-9]{6}$ ]] || continue
                [[ "$resolved" != "$NEW_BIN" && "$resolved" != "$previous_bin" ]] || continue
                [[ "$resolved" == "$BIN_ROOT/$name" ]] || return 1
                ;;
            *) return 1 ;;
        esac
        rm -rf -- "$resolved" || return 1
    done
}

# Wait for the configured display and a stable process, not just a momentary
# systemd 'active' state between crashes. Used before downloading and on commit.
wait_for_viewer() {
    local expected="$1" last_pid="" pid running stable=0 attempt
    for ((attempt=0; attempt<30; attempt++)); do
        pid="$(systemctl show -p MainPID --value "$SERVICE")" || return 1
        running=""
        if [[ "$pid" =~ ^[1-9][0-9]*$ ]]; then
            running="$(readlink -f "/proc/$pid/exe" 2>/dev/null)" || running=""
        fi
        if systemctl is-active --quiet "$SERVICE" && [[ -n "$running" && ( -z "$expected" || "$running" == "$expected" ) ]]; then
            if [[ "$pid" == "$last_pid" ]]; then stable=$((stable + 1)); else stable=1; fi
            if (( stable >= 10 )); then return 0; fi
        else
            stable=0
        fi
        last_pid="$pid"
        sleep 1
    done
    echo "$SERVICE did not stay active for 10 seconds. Recent logs:" >&2
    journalctl -u "$SERVICE" -n 12 --no-pager >&2 || true
    return 1
}

require_hdmi() {
    local env index="" status attempt
    env="$(systemctl show -p Environment --value "$SERVICE")" || return 1
    if [[ "$env" =~ SDL_KMSDRM_DEVICE_INDEX=([0-9]+) ]]; then index="${BASH_REMATCH[1]}"; fi
    echo "Checking HDMI (up to 15 seconds)."
    for ((attempt=0; attempt<15; attempt++)); do
        for status in /sys/class/drm/card${index:-*}-HDMI-A-*/status; do
            [[ -r "$status" ]] || continue
            if [[ "$(cat "$status")" == connected ]]; then return 0; fi
        done
        sleep 1
    done
    echo "HDMI display unavailable on the configured DRM card. Connect/turn on the display and retry. No receiver files were changed." >&2
    return 1
}

# Verify the compiled binary and required service arguments.
fullscreen_configured() {
    local command pid binary
    command="$(systemctl show -p ExecStart --value "$SERVICE")" || return 1
    [[ "$command" == *" --fullscreen"* ]] || return 1
    pid="$(systemctl show -p MainPID --value "$SERVICE")" || return 1
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
    binary="$(readlink -f "/proc/$pid/exe")" || return 1
    grep -aFq -- '--fullscreen' "$binary"
}

# Build identity lives with our release metadata and follows receiver rollback.
pi_stack_configured() {
    local command environment pid binary source actual
    fullscreen_configured || return 1
    command="$(systemctl show -p ExecStart --value "$SERVICE")" || return 1
    environment="$(systemctl show -p Environment --value "$SERVICE")" || return 1
    [[ "$command" == *" --app"* && "$command" == *" --hwdec"* && " $environment " == *" SFT_KMS_SCANOUT=1 "* ]] || return 1
    [[ " $environment " == *" SFT_SCANOUT_PACING=1 "* && " $environment " == *" SFT_DISPLAY_POLICY=auto "* ]] || return 1
    pid="$(systemctl show -p MainPID --value "$SERVICE")" || return 1
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
    binary="$(readlink -f "/proc/$pid/exe")" || return 1
    source="$(readlink -f "$SOURCE_LINK")" || return 1
    [[ -s "$source/.pi-build" ]] || return 1
    actual="$(sha256sum "$binary")" || return 1
    [[ "$(cat "$source/.pi-build")" == "$DOCK_VERSION $PI_STACK_HASH ${actual%% *}" ]]
}


MODE=install
if [[ "${1:-}" == --cleanup && $# == 1 ]]; then MODE=cleanup
elif [[ "${1:-}" == --check && $# == 1 ]]; then MODE=check
elif (( $# )); then echo "Use pi-switch-dock-update." >&2; exit 2; fi
(( EUID == 0 )) || { echo "Run with sudo." >&2; exit 1; }

if [[ "$MODE" == install && -f /opt/pi-switch-dock/reboot-required ]]; then
    if [[ "$(cat /opt/pi-switch-dock/reboot-required)" == "$(cat /proc/sys/kernel/random/boot_id)" ]]; then
        echo "Reboot the Pi to apply the prepared boot settings, then retry this command." >&2
        exit 1
    fi
fi

for command in tar sha256sum sync python3 make patch pkg-config; do
    command -v "$command" >/dev/null || { echo "Missing command: $command. Run the installer first." >&2; exit 1; }
done

PREFERENCES_HELPER="$BUNDLE/viewer-config.sh"
. "$PREFERENCES_HELPER"
. "$BUNDLE/tools.sh"
PI_PATCHES=(v4l2-m2m.patch fullscreen.patch low-latency-display.patch frame-pacing.patch display-policy.patch)
PATCH_DIR="$BUNDLE/patches"
# Entire published bundle identifies scripts, patched source and executable.
PI_STACK_HASH="$(sha256sum "$BUNDLE/release.json")"
PI_STACK_HASH="${PI_STACK_HASH%% *}"

[[ "$(uname -m)" == aarch64 || "$(uname -m)" == arm64 ]] || {
    echo "This installer supports Raspberry Pi OS 64-bit (aarch64) only." >&2
    exit 1
}

WORK="$(mktemp -d /tmp/pi-switch-dock-update.XXXXXX)"
cleanup() { rm -rf -- "$WORK"; }
trap cleanup EXIT

cleanup_installed_versions() {
    local pid
    pid="$(systemctl show -p MainPID --value "$SERVICE")"
    NEW_BIN="$(readlink -f "/proc/$pid/exe")" || return 1
    [[ -x "$NEW_BIN" && -L "$SOURCE_LINK" && -d "$(readlink -f "$SOURCE_LINK")" ]] || return 1
    BUILD_DIR="$(dirname "$(readlink -f "$SOURCE_LINK")")"
    ROLLBACK_ARCHIVE=""
    if [[ -d "$BACKUP_ROOT" ]]; then
        ROLLBACK_ARCHIVE="$(find "$BACKUP_ROOT" -maxdepth 1 -type f -name '*.tar.gz' -printf '%T@ %p\n' | sort -nr | sed -n '1s/^[^ ]* //p')"
    fi
    if [[ -z "$ROLLBACK_ARCHIVE" ]]; then echo "No rollback archive to prune."; return 0; fi
    prune_previous_versions
}

if [[ "$MODE" == cleanup ]]; then
    systemctl is-active --quiet "$SERVICE" || { echo "Receiver must be active before cleanup." >&2; exit 1; }
    cleanup_installed_versions
    persist_installation
    echo "Only the latest rollback archive and current/previous builds are retained."
    exit 0
fi

# Fail before receiver replacement if HDMI or the existing service is
# unavailable. Preflight never restarts or changes the existing receiver.
if [[ "$MODE" == install ]] && systemctl cat "$SERVICE" >/dev/null 2>&1; then
    require_hdmi
    systemctl is-active --quiet "$SERVICE" || { echo "Receiver is inactive; diagnose/start it before updating." >&2; exit 1; }
    wait_for_viewer ""
fi

TAG="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["upstream_tag"])' "$BUNDLE/release.json")"
DOCK_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$BUNDLE/release.json")"

SRC="$WORK/source"
mkdir -p "$SRC"
pkg-config --exists sdl2 libusb-1.0 libavcodec libavutil libavformat libdrm || {
    echo "Build dependencies missing; run install.sh first." >&2; exit 1;
}
python3 "$BUNDLE/prepare-source.py" "$BUNDLE/release.json" "$SRC"
bash "$BUNDLE/build-receiver.sh" "$SRC" "$TAG"
BUILT_BIN="$SRC/tools/raw-recv/raw-view"
python3 - "$BUILT_BIN" <<'PY'
from pathlib import Path
import sys
elf=Path(sys.argv[1]).read_bytes()[:20]
if len(elf)<20 or elf[:6]!=b"\x7fELF\x02\x01" or elf[18:20]!=b"\xb7\x00":
    sys.exit("Build is not an ARM64 executable")
PY
for feature in "Switch Frame Tap $TAG" h264_v4l2m2m --fullscreen 'decode: repeated V4L2 errors' 'video: direct DRM DMA-BUF scanout active' SFT_SCANOUT_PACING 'video: high-resolution display policy:'; do
    grep -aFq -- "$feature" "$BUILT_BIN" || { echo "Built receiver missing feature: $feature" >&2; exit 1; }
done
if [[ "${1:-}" == --check ]]; then
    echo "CHECK PASSED: pinned source, patches and ARM64 build. Receiver unchanged."
    exit 0
fi
BUILT_HASH="$(sha256sum "$BUILT_BIN")"
. /etc/os-release
[[ "${VERSION_CODENAME:-}" == trixie ]] || { echo "Requires Debian Trixie runtime." >&2; exit 1; }
# Resolve the compiled executable's libraries without stopping the working viewer.
LIBRARIES="$(ldd "$BUILT_BIN")" || { echo "Cannot resolve receiver runtime libraries." >&2; exit 1; }
if [[ "$LIBRARIES" == *"not found"* ]]; then
    echo "Receiver runtime libraries missing; run the project installer first." >&2
    exit 1
fi
echo "Installing built pi-switch-dock $DOCK_VERSION (Switch Frame Tap $TAG)."


BOOTSTRAP=0
if ! systemctl cat "$SERVICE" >/dev/null 2>&1; then
    BOOTSTRAP=1
    if [[ -e "$UNIT" || -e "$DROPIN" ]]; then
        echo "Found incomplete receiver service files. Refusing to overwrite them; inspect $UNIT and $DROPIN." >&2
        exit 1
    fi
else
    [[ -s "$UNIT" && -s "$DROPIN" ]] || {
        echo "Receiver service exists but its managed unit/drop-in is incomplete." >&2
        exit 1
    }
    systemctl is-active --quiet "$SERVICE" || {
        echo "$SERVICE is not active. Start or diagnose it before updating." >&2
        exit 1
    }
fi

OLD_SOURCE_TARGET=""
ACTIVE_BIN=""
ACTIVE_SOURCE_LINK="$SOURCE_LINK"
if (( ! BOOTSTRAP )); then
    CURRENT_PID="$(systemctl show -p MainPID --value "$SERVICE")"
    [[ "$CURRENT_PID" =~ ^[1-9][0-9]*$ ]] || { echo "Could not identify the active viewer process." >&2; exit 1; }
    ACTIVE_BIN="$(readlink -f "/proc/$CURRENT_PID/exe")"
    [[ -x "$ACTIVE_BIN" ]] || { echo "Active viewer binary not found: $ACTIVE_BIN" >&2; exit 1; }
    [[ -L "$ACTIVE_SOURCE_LINK" ]] || { echo "Managed source link is missing: $SOURCE_LINK" >&2; exit 1; }
    OLD_SOURCE_TARGET="$(readlink -f "$ACTIVE_SOURCE_LINK")"
    [[ -s "$OLD_SOURCE_TARGET/.pi-release.json" ]] || { echo "Managed release manifest missing; clean installation required." >&2; exit 1; }
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
SAFE_TAG="$DOCK_VERSION"
BUILD_DIR="$BUILD_ROOT/$STAMP-$SAFE_TAG"
NEW_BIN="$BIN_ROOT/switch-frame-tap-viewer-$SAFE_TAG-v4l2-$STAMP"
mkdir -p "$BUILD_DIR/release" "$BUILD_ROOT" "$STATE_DIR"
# Retain only our exact patches and build identity, without upstream source.
mkdir -p "$SRC/.pi-patches"
for name in "${PI_PATCHES[@]}"; do cp -a "$PATCH_DIR/$name" "$SRC/.pi-patches/"; done
printf '%s %s %s\n' "$DOCK_VERSION" "$PI_STACK_HASH" "${BUILT_HASH%% *}" > "$SRC/.pi-build"
cp -a "$SRC/.pi-build" "$BUILD_DIR/release/"
cp -a "$BUNDLE/release.json" "$BUILD_DIR/release/.pi-release.json"
cp -a "$SRC/.pi-patches" "$BUILD_DIR/release/"
install -m 755 "$BUILT_BIN" "$NEW_BIN"

if (( BOOTSTRAP )); then
    CONNECTED=""
    for status in /sys/class/drm/card*-HDMI-A-*/status; do
        [[ -r "$status" ]] || continue
        [[ "$(cat "$status")" == connected ]] || continue
        if [[ -z "$CONNECTED" || "$(basename "$(dirname "$status")")" == card1-HDMI-A-1 ]]; then
            CONNECTED="$status"
        fi
    done
    if [[ -z "$CONNECTED" ]]; then
        echo "No connected HDMI status found; using Raspberry Pi 4 HDMI-1 defaults (DRM 1 / vc4hdmi0)."
        CONNECTOR="card1-HDMI-A-1"
    else
        CONNECTOR="$(basename "$(dirname "$CONNECTED")")"
    fi
    DRM_CARD="${CONNECTOR%%-*}"
    DRM_INDEX="${DRM_CARD#card}"
    HDMI_NAME="${CONNECTOR##*-}"
    case "$HDMI_NAME" in
        1) AUDIO_CARD=vc4hdmi0 ;;
        2) AUDIO_CARD=vc4hdmi1 ;;
        *) echo "Unsupported HDMI connector name: $CONNECTOR" >&2; exit 1 ;;
    esac
    grep -q "$AUDIO_CARD" /proc/asound/cards || {
        echo "HDMI audio device $AUDIO_CARD was not found. Check the display and audio devices." >&2
        exit 1
    }
    install -d -m 755 "$(dirname "$UNIT")" "$(dirname "$DROPIN")"
    cat > "$UNIT" <<EOF
[Unit]
Description=Switch Frame Tap HDMI receiver
After=systemd-logind.service lite-dock-splash.service

[Service]
Type=simple
Environment=HOME=/root
Environment=XDG_DATA_HOME=/root/.local/share
Environment=SDL_VIDEODRIVER=kmsdrm
Environment=SDL_KMSDRM_DEVICE_INDEX=$DRM_INDEX
Environment=SDL_AUDIODRIVER=alsa
Environment=AUDIODEV=plughw:CARD=$AUDIO_CARD,DEV=0
Environment=SFT_KMS_SCANOUT=1
Environment=SFT_SCANOUT_PACING=1
Environment=SFT_DISPLAY_POLICY=auto
ExecStartPre=-/usr/bin/systemctl stop lite-dock-splash.service
ExecStart=$NEW_BIN --app --fullscreen --hwdec
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
else
    BACKUP_DIR="$BACKUP_ROOT/$STAMP-$SAFE_TAG"
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_ROOT" "$BACKUP_DIR"
    printf '%s\n' pi-switch-dock-rollback-v1 > "$BACKUP_DIR/format"
    cp -a "$ACTIVE_BIN" "$BACKUP_DIR/current-custom-viewer"
    cp -a "$DROPIN" "$BACKUP_DIR/current-viewer-override.conf"
    printf '%s\n' "$ACTIVE_BIN" > "$BACKUP_DIR/active-binary-path"
    printf '%s\n' "$OLD_SOURCE_TARGET" > "$BACKUP_DIR/active-source-path"
    cp -a "$STATE_FILE" "$BACKUP_DIR/active-release"
    cp -a "$UNIT" "$BACKUP_DIR/"
    cp -a "$(dirname "$DROPIN")" "$BACKUP_DIR/service.d"
    save_viewer_preferences "$BACKUP_DIR/viewer-preferences"
    tar -C "$(dirname "$OLD_SOURCE_TARGET")" -czf "$BACKUP_DIR/release-metadata.tar.gz" "$(basename "$OLD_SOURCE_TARGET")"
    (cd "$BACKUP_DIR" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
    # A failed candidate must not become the default rollback archive.
    tar -C "$BACKUP_ROOT" -czf "$BACKUP_DIR.tar.gz.pending" "$(basename "$BACKUP_DIR")"
    chmod 600 "$BACKUP_DIR.tar.gz.pending"
    (cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS >/dev/null)
fi

PREVIOUS_TOOLS="$(readlink -f /opt/pi-switch-dock/tools-current || true)"
PREVIOUS_DROPIN=""
if [[ -f "$DROPIN" ]]; then PREVIOUS_DROPIN="$WORK/previous-dropin"; cp -a "$DROPIN" "$PREVIOUS_DROPIN"; fi
PREVIOUS_SOURCE=""
if [[ -L "$ACTIVE_SOURCE_LINK" ]]; then PREVIOUS_SOURCE="$(readlink -f "$ACTIVE_SOURCE_LINK")"; fi
if [[ -f "$STATE_FILE" ]]; then cp -a "$STATE_FILE" "$WORK/previous-release"; fi
save_viewer_preferences "$WORK/previous-preferences"
rollback_on_error() {
    rc=$?
    trap - ERR
    set +e
    echo "Install/update failed; restoring the previous receiver state." >&2
    systemctl stop "$SERVICE" || true
    if [[ -n "$PREVIOUS_TOOLS" ]]; then ln -sfn "$PREVIOUS_TOOLS" /opt/pi-switch-dock/tools-current; fi
    restore_viewer_preferences "$WORK/previous-preferences" || true
    if [[ -n "$PREVIOUS_DROPIN" ]]; then cp -a "$PREVIOUS_DROPIN" "$DROPIN"; else rm -f "$DROPIN"; fi
    if (( BOOTSTRAP )); then
        systemctl disable --now "$SERVICE" >/dev/null 2>&1 || true
        rm -f "$UNIT"
    fi
    if [[ -n "$PREVIOUS_SOURCE" ]]; then ln -sfn "$PREVIOUS_SOURCE" "$SOURCE_LINK"; else rm -f "$SOURCE_LINK"; fi
    if [[ -f "$WORK/previous-release" ]]; then cp -a "$WORK/previous-release" "$STATE_FILE"; else rm -f "$STATE_FILE"; fi
    systemctl daemon-reload || true
    if (( BOOTSTRAP )); then systemctl reset-failed "$SERVICE" >/dev/null 2>&1 || true; else systemctl restart "$SERVICE" || true; fi
    exit "$rc"
}
trap rollback_on_error ERR

cat > "$DROPIN" <<EOF
[Service]
Environment=SFT_KMS_SCANOUT=1
Environment=SFT_SCANOUT_PACING=1
Environment=SFT_DISPLAY_POLICY=auto
ExecStart=
ExecStart=$NEW_BIN --app --fullscreen --hwdec
EOF
systemctl daemon-reload
if (( BOOTSTRAP )); then
    systemctl enable --now "$SERVICE"
else
    systemctl restart "$SERVICE"
fi
wait_for_viewer "$NEW_BIN"
ln -sfn "$BUILD_DIR/release" "$SOURCE_LINK"
printf '%s\n' "$TAG" > "$STATE_FILE"
pi_stack_configured
activate_tools "$BUNDLE"
if (( ! BOOTSTRAP )); then mv -- "$BACKUP_DIR.tar.gz.pending" "$BACKUP_DIR.tar.gz"; fi
# Do not commit or prune the previous installation until the new binary,
# unit, enablement symlink, sources, release marker and rollback archive are
# on storage. A flush error still invokes rollback_on_error.
echo "Saving receiver installation to storage."
persist_installation
trap - ERR
trap cleanup EXIT

if (( ! BOOTSTRAP )); then
    ROLLBACK_ARCHIVE="$BACKUP_DIR.tar.gz"
    if ! prune_previous_versions; then
        echo "Warning: update succeeded, but old-version cleanup was incomplete; inspect $BACKUP_ROOT and $BUILD_ROOT." >&2
    fi
fi

# Cleanup also changes directory metadata. Never announce success if this
# final flush fails, even though the installed receiver may already be active.
persist_installation
echo "Installed pi-switch-dock $DOCK_VERSION (Switch Frame Tap $TAG)."
echo "The receiver is active."
if systemctl is-enabled --quiet "$SERVICE"; then echo "Startup at boot is enabled."; fi
if (( ! BOOTSTRAP )); then
    echo "Rollback archive: $BACKUP_DIR.tar.gz"
fi
