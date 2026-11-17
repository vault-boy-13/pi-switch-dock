# Candidate testing and release flow

Each upstream Switch Frame Tap release goes through the same cycle:

1. Pin the upstream tag and source-archive SHA256 in `release-spec.json`.
   Review the upstream changes and apply all five Pi patches in order to a
   clean source tree. Keep the HDMI 1080p120/60 policy and cadence-based frame
   pacing intact.
2. Run the Linux test suite and package the project tools. Validate the exact
   bundle with `release_client.unpack`; it must contain only project scripts,
   patches and splash assets, never upstream source or a built receiver.
3. On the project Pi, extract that bundle to a temporary directory. Run
   `deploy.sh --check` under `/run/lock/pi-switch-dock-update.lock`; this
   downloads the pinned upstream source, applies the patches and builds an
   ARM64 candidate without changing the running receiver. If that passes,
   activate the candidate using the same bundle's `deploy.sh` under the lock.
   The deployment prints the exact rollback archive path. Keep the previous
   receiver until the hardware checks below pass.
4. Acceptance requires a connected Switch over USB and checks of video, audio,
   actual HDMI mode, per-frame intervals, disconnect/reconnect, service restart
   count and SSH access after reboot. Test the release-specific user-visible
   changes as well. Record hardware results separately from code tests; a
   successful build, active service or average FPS alone is not acceptance.
5. After acceptance, restore the previous receiver with
   `pi-switch-dock-rollback <exact-rollback-archive>`. Confirm its release
   marker, running executable and active service before preparing the
   publication bundle. This keeps the project Pi on the last published version
   while the new release is awaiting publication.
6. Prepare the final bundle and checksum, then commit and push the project
   changes, create the matching tag, and publish a stable GitHub release with
   both assets. Never replace already published assets.
7. Once the stable release is visible, run `pi-switch-dock-update --check`,
   then install it with `pi-switch-dock-update` on the project Pi. Confirm that
   the installed project version, upstream source tag, running executable and
   service state match the published release. This validates the same public
   download path other users will use.

The installed update wrapper accepts only published stable releases. For
pre-publication candidate testing, use the verified local release bundle and
its `deploy.sh` as described above; do not point the public updater at upstream
`latest`, a branch, or an unpublished tag.

## Version and patches

Set `version`, `upstream_tag` and `upstream_sha256` in `release-spec.json`.
The release tag must match the supported upstream tag. Installed clients
compare release tags when checking for updates.

Apply and review the five Pi patches against the pinned source in a temporary
directory. Preserve USB decoding, HDMI 1080p120/60 selection, frame pacing and
the disconnect-to-waiting-screen transition.

## Validation and packaging

Run the tests on Linux, then build the release package:

```sh
python3 -m unittest discover -s tests -v
python3 package-release.py
```

The output is `dist/pi-switch-dock-tools.tar.gz` and `dist/SHA256SUMS`.
The packager verifies the closed file list and records checksums in `release.json`.
Keep `dist/`, test reports, caches and device logs out of Git. Keep upstream
source, compiled receivers and device rollback archives out of release assets.

Validate the exact package on the project Pi. After extracting it with
`release_client.unpack(bundle, destination, tag)`, a build-only check is:

```sh
sudo flock -n /run/lock/pi-switch-dock-update.lock \
  env PI_SWITCH_DOCK_RELEASE_LOCKED=1 bash /path/to/verified-tools/deploy.sh --check
```

This checks the pinned download, patches and ARM64 build without replacing
the receiver. If it passes, activate the candidate from that same extracted
bundle, complete the hardware acceptance in step 4 above, and restore the
captured previous version before publication. Initial-install and splash/fan
checks are needed only when those components change or for a fresh install.

For initial installation, also check the English startup screen, absence of
console text and handoff to the receiver. Receiver update and rollback must
preserve the installed splash binary, assets, unit and boot files. Splash
installation belongs only in `setup.sh`; keep it out of receiver maintenance.
Check that initial setup installs and enables `switch-dock-fan.service`, that
the measured duty levels work on the two-wire fan, and that its stop/error path
sets GPIO18 high. The fan source and unit are part of the closed release bundle.

## Publication

Only the current installation layout and package format are supported. On
Windows, `release.ps1` publishes the already prepared and Pi-validated files
from `dist/`; it does not rebuild the bundle. Before running it, commit and push
the project changes, including the matching `release-spec.json`, and push the
branch to `origin`. Authenticate GitHub CLI once with `gh auth login`.

From the `pi-switch-dock` directory, create and upload a draft release:

```powershell
.\release.ps1
```

The script checks the spec version, archive checksum, clean working tree,
pushed branch, repository origin and GitHub CLI authentication. It creates and
pushes the annotated version tag, then uploads the archive and `SHA256SUMS` to
a draft stable release. Review the draft and publish it on GitHub, or run:

```powershell
.\release.ps1 -Publish
```

Use `-Publish` on the initial run only when you want the script to publish
immediately. To publish a draft later, use GitHub or
`gh release edit <tag> --repo vault-boy-13/pi-switch-dock --draft=false`.
The script refuses to replace an existing tag or release. If a run stops after
pushing the tag, inspect GitHub before retrying.

After the project owner publishes the stable release, validate it through the
installed updater as described in step 7. Changes to `main`, drafts and
prereleases do not make an update available. Packaging and testing do not
publish anything.
