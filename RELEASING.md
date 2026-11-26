# Candidate testing and release flow

## Prepare locally

Pin `version`, `upstream_tag` and `upstream_sha256` in `release-spec.json`.
Both tags must match. Review upstream changes and all six Pi patches;
preserve HDMI 1080p120/60 selection, 1080p direct scanout and USB video/audio.
Keep optional vblank pacing disabled by default.

### Unreleased economy mode (local validation, 2026-11-25)

Hold publication until upstream **stable v0.7.24** is available. Do not publish
these changes as v0.7.23 or against a beta. `release-spec.json` intentionally
remains pinned to v0.7.23 for reproducibility checks. Before release, review
the final upstream tag, adapt the complete patch stack with zero fuzz, update
the source checksum, and repeat build and hardware acceptance.

`idle-power.patch` follows `display-policy.patch`. Both initial installation
and receiver updates set `SFT_IDLE_TIMEOUT=600`. Accepted fresh video or game
audio resets a monotonic timer; status packets, truncated payloads, unsupported
PCM formats and video older than 800 ms do not. After the timeout, the viewer stops the
decoder thread, releases decoded/scanout buffers and textures, closes audio
and its SDL subsystem, and leaves a static HDMI image. USB remains available;
fresh media restores the decoder/audio and requests a keyframe. The normal
streaming path and HDMI mode policy remain enabled. GPIO fan control remains
temperature based.

The project patch targets the pinned v0.7.23 source. A separately adapted
v0.7.24-beta3 local Pi prototype validated the 600-second initial timeout and
shortened 15-second stream disconnect/reconnect cycles; the user confirmed
image, sound and smoothness on both initial and repeated wake. The Pi is left
with the 600-second timeout. CPU time was below the 10 ms accounting resolution
over a 15-second idle sample after replacing SDL's KMS event wait with an OS
sleep. This is not a wattage measurement or a week-long physical idle test.

Pure policy tests cover the exact boundary, activity resets, long idle, clock
and activity-counter wrap, transport changes and disabled mode. An isolated
Pi integration test exercises the real reader and 20 V4L2/audio release/resume
cycles, including stale/status/truncated input, muted audio, buffer reference
release and renderer replacement. To explicitly run it against a separately
patched source tree (it uses dummy video/audio, never USB):

```sh
RUN_PI_IDLE_INTEGRATION=1 PI_IDLE_TEST_SOURCE=/absolute/path/to/tools/raw-recv/raw-view.c \
  python3 -m unittest discover -s tests -p test_idle_power.py -v
```

The local device override `zzzzzzzz-idle-local.conf` selects the beta prototype;
the previously installed `zzzzzz-sft-beta3.conf` is also local. Preserve both in
a backup and retire them explicitly when migrating to stable v0.7.24, or they
would override the managed receiver. Local rollback is available at
`/root/pi-switch-dock/backups/idle-20261125-082954/rollback-idle.sh`; the same
directory retains the original binary, units and preferences in `state.tar.gz`.

Upstream beta3 audit: its adaptive audio cushion is automatic and Smooth
pacing was already enabled in the tested viewer preferences. Keep those
upstream implementations. They do not replace Pi V4L2 decoding, DMA-BUF
scanout or advertised 1080p120/60 mode selection. Keep our optional vblank
pacing disabled to avoid stacking two pacing mechanisms; removal of its
remaining code needs separate 60/120 Hz validation against stable v0.7.24.
Upstream's Windows tray Dock mode does not implement this headless Pi idle
policy. No console update is part of this work.

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

For the local HDMI/CEC prototype, install `lite-dock-hdmi.py` in
`/usr/local/sbin`, `lite-dock-hdmi.service` in `/etc/systemd/system`, and
`hdmi-ready.conf` in the viewer service drop-in directory. Enable the HDMI
service after reloading systemd. These files are staged for local device testing
and are outside the current release archive. The monitor uses this viewer's
Linux statistics log to detect picture or audio after a pause. When HDMI has no
usable mode, USB enumeration is the trigger because the viewer cannot run yet.
Validate cold boot with the TV in standby, delayed HDMI availability, media
start without a Pi reboot, and a TV with CEC disabled before packaging.

On the test Pi, the TV woke at service startup. After the TV was switched off
with its remote, `Image View On` alone left it in standby. Sending it followed by
`Active Source` woke the TV. Reconnecting the Switch reproduced automatic wake
with working video and audio. The no-mode systemd condition was checked on the
Pi with a temporary service, and a ten-hour wait was simulated in a test.
A physical cold boot and delayed display test are still pending. The Pi's
rollback script is under `/root/pi-switch-dock/backups/hdmi-wake-20261126-225741/`.

The local drop-in also chooses the HDMI audio device at viewer startup.
HDMI-A-1 uses `vc4hdmi0` and HDMI-A-2 uses `vc4hdmi1`. Moving the cable to
the other port restarts the viewer with the matching device. A connected
port with a valid EDID is eligible even when the kernel's mode list is still
empty. The test Pi opened the correct PCM device on each port. The user
confirmed video and game audio after moving the cable to HDMI-A-1.
