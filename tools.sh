#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
activate_tools() {
    local bundle="$1" root=/opt/pi-switch-dock tag identity destination staging file wrapper
    tag="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$bundle/release.json")"
    identity="$(sha256sum "$bundle/release.json")"
    destination="$root/tools/$tag-${identity:0:16}"
    install -d -m 755 "$root/tools"
    if [[ ! -d "$destination" ]]; then
        staging="$(mktemp -d "$root/tools/.staging.XXXXXX")"
        for file in install.sh setup.sh deploy.sh rollback.sh release_client.py prepare-source.py build-receiver.sh tools.sh boot_config.py viewer-config.sh install-splash.sh splash release.json LICENSE NOTICE patches; do
            cp -a "$bundle/$file" "$staging/$file"
        done
        mv -T -- "$staging" "$destination"
    fi
    ln -s "$destination" "$root/tools-current.new.$$"
    mv -Tf -- "$root/tools-current.new.$$" "$root/tools-current"
    for file in update rollback; do
        wrapper="/usr/local/sbin/pi-switch-dock-$file.new.$$"
        if [[ "$file" == update ]]; then
            printf '%s\n' '#!/usr/bin/env bash' 'exec python3 /opt/pi-switch-dock/tools-current/release_client.py update "$@"' > "$wrapper"
        else
            printf '%s\n' '#!/usr/bin/env bash' 'exec bash /opt/pi-switch-dock/tools-current/rollback.sh "$@"' > "$wrapper"
        fi
        chmod 755 "$wrapper"
        mv -f -- "$wrapper" "/usr/local/sbin/pi-switch-dock-$file"
    done
    sync -f "$root" /usr/local/sbin /root
}
