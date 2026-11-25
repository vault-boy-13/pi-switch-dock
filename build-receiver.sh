#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -Eeuo pipefail
[[ $# == 2 ]] || { echo 'Usage: build-receiver.sh clean-source upstream-tag' >&2; exit 2; }
SRC="$(realpath "$1")"
TAG="$2"
PATCH_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/patches" && pwd)"
PI_PATCHES=(v4l2-m2m.patch fullscreen.patch low-latency-display.patch frame-pacing.patch display-policy.patch idle-power.patch)
apply_pi_patches() {
    local name
    for name in "${PI_PATCHES[@]}"; do
        echo "Checking and applying Pi patch: $name"
        if ! patch --batch --forward --fuzz=0 --dry-run --silent -d "$SRC" -p1 < "$PATCH_DIR/$name"; then
            echo "Pi patch $name is incompatible with pinned source $TAG. Current receiver was not replaced." >&2
            return 1
        fi
        patch --batch --forward --fuzz=0 --silent -d "$SRC" -p1 < "$PATCH_DIR/$name" || return 1
    done
}

# Normalize upstream line endings before exact-context patching.
python3 - "$SRC" <<'PY'
from pathlib import Path
import sys
for p in (Path(sys.argv[1]) / "tools/raw-recv").rglob("*"):
    if p.is_file() and p.suffix in {".c", ".h"}:
        data=p.read_bytes()
        if b"\r\n" in data: p.write_bytes(data.replace(b"\r\n", b"\n"))
PY
apply_pi_patches
make -C "$SRC/tools/raw-recv" raw-view "CFLAGS=-O2 -Wall -Wextra -DSFT_VERSION=\\\"$TAG\\\""
