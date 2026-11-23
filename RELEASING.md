# Candidate testing and release flow

## Prepare locally

Pin `version`, `upstream_tag` and `upstream_sha256` in `release-spec.json`.
Both tags must match. Review upstream changes and all five Pi patches;
preserve HDMI 1080p120/60 selection, frame pacing and USB video/audio.

Run on Linux, then package:

```sh
python3 -m unittest discover -s tests -v
python3 package-release.py
```

The packager validates the closed file list, manifest and hashes. Outputs are
`dist/pi-switch-dock-tools.tar.gz` and `dist/SHA256SUMS`. Keep `dist/`, caches,
logs and test reports out of Git. Never publish upstream source, compiled
receivers or device rollback archives as release assets.

An optional local Pi build/deployment can precede public candidate testing.
Extract the bundle using `release_client.unpack`; run its `deploy.sh --check`
under the maintenance lock to build without replacing the receiver:

```sh
sudo flock -n /run/lock/pi-switch-dock-update.lock \
  env PI_SWITCH_DOCK_RELEASE_LOCKED=1 bash /path/to/verified-tools/deploy.sh --check
```

Use the same command without `--check` to activate. If the fan service is
installed, deployment updates its script/unit from the same verified bundle
and records the prior files and active/enabled state in a separate
`/root/pi-switch-dock/backups/fan-<timestamp>/` backup. A missing optional fan
service stays absent. After hardware checks, restore the exact receiver
rollback archive printed by deployment. This restores the receiver but leaves
the release fan curve installed; if rejecting the fan change too, separately
restore its script/unit and active/enabled state from the printed fan backup.

## Publish a candidate

Commit and push to `origin`. On Windows, install GitHub CLI and Python, then
authenticate once with `gh auth login`. From the project directory:

```powershell
.\release.ps1 -Candidate
```

This creates and pushes the annotated version tag, uploads the existing `dist/`
files and exposes a **prerelease**. Ordinary installation/update ignores it.
No arguments creates a draft prerelease instead. To expose that draft later:

```powershell
gh release edit v0.7.23 --repo vault-boy-13/pi-switch-dock --prerelease --draft=false
```

If a draft was prepared before a tools change, first confirm `isDraft` is true:

```powershell
gh release view v0.7.23 --repo vault-boy-13/pi-switch-dock --json isDraft,isPrerelease
```

Only while it is still a private draft, upload the newly packaged files before
exposing it. Never use `--clobber` on a public candidate or stable release:

```powershell
gh release upload v0.7.23 .\dist\pi-switch-dock-tools.tar.gz .\dist\SHA256SUMS --repo vault-boy-13/pi-switch-dock --clobber
```

The script refuses to overwrite existing tags/releases. Never replace public
candidate assets. If validation needs changes, prepare a new version. The
current format requires project and upstream versions to match, so repeated
candidate revisions for one upstream tag need a version-format extension first.

## Install candidate, test, roll back

On a Pi with the candidate-aware updater:

```sh
sudo pi-switch-dock-update --candidate v0.7.23 --check
sudo pi-switch-dock-update --candidate v0.7.23
```

`--candidate TAG` requires an explicit public project prerelease; drafts,
branches and stable releases are rejected. It affects only this invocation.
The same lock, download checksums, archive validation, ARM64 build, deployment
and rollback backup apply. `--reinstall` also works with an explicit candidate.

For an older installed updater without this flag, copy the reviewed local
`release_client.py` to a temporary directory on the project Pi and invoke it
directly for the first candidate check/install:

```sh
sudo python3 /path/to/reviewed/release_client.py update --candidate v0.7.23 --check
sudo python3 /path/to/reviewed/release_client.py update --candidate v0.7.23
```

This uses the same lock and installs the release tools. Changes to `main` alone
do not migrate an installed updater.

Acceptance requires connected USB Switch video/audio, actual HDMI mode,
per-frame intervals, disconnect/reconnect, restart count, SSH after reboot and
upstream user-visible changes. Record hardware observations separately from
code tests; an active service or average FPS alone is not acceptance.

After acceptance, restore the **exact archive printed by candidate deployment**:

```sh
sudo pi-switch-dock-rollback /root/pi-switch-dock/backups/<exact-archive>.tar.gz
```

Confirm the previous release manifest, executable, preferences and active
service. Rollback restores receiver metadata; updater tools remain installed.
Leave the Pi on its previous stable version before promotion.

## Promote and verify the stable path

Keep the same local `dist/` files. After candidate acceptance and rollback:

```powershell
.\release.ps1 -Publish
```

This **promotes an existing public prerelease**. It downloads both assets and
compares them with local `dist/`, then removes the prerelease flag and marks it
Latest. It does not rebuild or replace assets and refuses to promote a draft.

On the Pi restored to the previous stable version:

```sh
sudo pi-switch-dock-update --check
sudo pi-switch-dock-update
```

Confirm the installed project version, pinned upstream tag, running executable,
service state, video and audio. Both candidate and stable paths are now checked.
Without rollback the same-tag update correctly does nothing.

Fresh-install splash/fan/CEC checks are required when those components change.
Initial setup owns splash installation; receiver maintenance must preserve its
assets and boot files. Check GPIO18 levels, temperature transitions, no-boost
startup, shutdown and sensor-error behavior when changing fan support. Check
the HDMI-CEC OSD name on a CEC-enabled TV; the TV may retain its own input
label regardless of the advertised name.
Only the current layout/package format is supported.
