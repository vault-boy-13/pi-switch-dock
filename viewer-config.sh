#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# The service explicitly sets HOME and XDG_DATA_HOME.
PI_VIEWER_CONFIG_PATH=/root/.local/share/switch-frame-tap/viewer/viewer.ini

save_viewer_preferences() {
    local destination="$1"
    mkdir -p "$destination"
    rm -f -- "$destination/viewer.ini"
    if [[ -f "$PI_VIEWER_CONFIG_PATH" ]]; then
        cp -a -- "$PI_VIEWER_CONFIG_PATH" "$destination/viewer.ini"
    fi
    printf '%s\n' 'pi-viewer-preferences-v1' > "$destination/format"
}

restore_viewer_preferences() {
    local saved="$1"
    [[ -f "$saved/format" && "$(cat "$saved/format")" == pi-viewer-preferences-v1 ]] || return 1
    if [[ -f "$saved/viewer.ini" ]]; then
        mkdir -p "$(dirname "$PI_VIEWER_CONFIG_PATH")"
        cp -a -- "$saved/viewer.ini" "$PI_VIEWER_CONFIG_PATH"
    else
        rm -f -- "$PI_VIEWER_CONFIG_PATH"
    fi
}
