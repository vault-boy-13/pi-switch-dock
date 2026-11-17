#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Bootstrap only. All installation code comes from our published release.
set -Eeuo pipefail
(( EUID == 0 )) || { echo 'Run with sudo.' >&2; exit 1; }
for command in curl python3; do
    command -v "$command" >/dev/null || { echo "Install $command first." >&2; exit 1; }
done
WORK="$(mktemp -d /tmp/pi-switch-dock-bootstrap.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
API=https://api.github.com/repos/vault-boy-13/pi-switch-dock/releases/latest
if ! curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 "$API" -o "$WORK/latest.json"; then
    echo 'No published pi-switch-dock release could be obtained. Receiver unchanged.' >&2
    exit 1
fi
TAG="$(python3 -c '
import json,re,sys
r=json.load(open(sys.argv[1])); tag=r["tag_name"]
if r.get("draft") or r.get("prerelease") or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+",tag):
    sys.exit("Expected a stable pi-switch-dock release")
print(tag)
' "$WORK/latest.json")"
# Pin the helper to the same project tag as the payload, never main.
curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 \
    "https://raw.githubusercontent.com/vault-boy-13/pi-switch-dock/$TAG/release_client.py" \
    -o "$WORK/release_client.py"
python3 "$WORK/release_client.py" install "$@" "$TAG"
