#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fetch only published pi-switch-dock releases; never query upstream latest."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request

REPOSITORY = "vault-boy-13/pi-switch-dock"
API = f"https://api.github.com/repos/{REPOSITORY}/releases"
ASSET = "pi-switch-dock-tools.tar.gz"
TARGET = "debian-trixie-arm64"
CURRENT = Path("/opt/pi-switch-dock/current/.pi-release.json")
REQUIRED = {"install.sh", "setup.sh", "deploy.sh", "rollback.sh",
            "release_client.py", "tools.sh", "boot_config.py", "viewer-config.sh",
            "LICENSE", "NOTICE", "build-receiver.sh", "prepare-source.py",
            "install-fan.sh", "switch-dock-fan.py", "switch-dock-fan.service"}
REQUIRED |= {"patches/" + name + ".patch" for name in
             ("v4l2-m2m", "fullscreen", "low-latency-display", "frame-pacing", "display-policy")}
REQUIRED |= {"install-splash.sh", "splash/splash.c", "splash/boot-presentation.py",
             "splash/lite-dock-splash.service"}
REQUIRED |= {"splash/" + name + ".bmp" for name in ("card", "halo", "dot", "bar")}


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError("Expected a release tag in vMAJOR.MINOR.PATCH format")
    return tuple(map(int, value[1:].split(".")))


def fetch(url):
    if not url.startswith("https://"):
        raise ValueError("Release downloads require HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": "pi-switch-dock",
                                                  "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def find_release(tag=None, candidate=False):
    if candidate and not tag:
        raise ValueError("Candidate installation requires an explicit project tag")
    if tag:
        version(tag)
    try:
        release = json.loads(fetch(API + ("/tags/" + tag if tag else "/latest")))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ValueError("No published pi-switch-dock release available. Receiver unchanged.") from error
        raise
    version(release["tag_name"])
    if release.get("draft") or (tag and release["tag_name"] != tag):
        raise ValueError("Only published releases matching the requested tag are accepted")
    if bool(release.get("prerelease")) != candidate:
        raise ValueError("Candidate mode requires a published prerelease" if candidate else
                         "Only published stable pi-switch-dock releases are accepted")
    assets = {item["name"]: item for item in release["assets"]}
    if ASSET not in assets or "SHA256SUMS" not in assets:
        raise ValueError("Project release is incomplete: tools bundle/checksum missing")
    # Asset URLs must belong to this project and this exact tag.
    prefix = f"https://github.com/{REPOSITORY}/releases/download/{release['tag_name']}/"
    for name in (ASSET, "SHA256SUMS"):
        if assets[name]["browser_download_url"] != prefix + name:
            raise ValueError("Unexpected project release asset URL")
    return release, assets


def installed_version():
    if not CURRENT.exists():
        if CURRENT.parent.exists() or CURRENT.parent.is_symlink():
            raise ValueError("Installed release has no manifest; a clean installation is required")
        return None
    value = json.loads(CURRENT.read_text())["version"]
    version(value)
    return value


def newer(candidate, current):
    return current is None or version(candidate) > version(current)


def safe_name(name):
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or any(p in ("", ".", "..") for p in name.split("/")):
        raise ValueError("Unsafe release path: " + name)
    return path


def unpack(bundle, destination, expected):
    """Validate all archive entries and hashes before executing release scripts."""
    with tarfile.open(bundle, "r:gz") as archive:
        members = archive.getmembers()
        names = set()
        total = 0
        for member in members:
            safe_name(member.name)
            if member.name in names or not (member.isdir() or member.isfile()):
                raise ValueError("Duplicate path or special/link entry in release")
            names.add(member.name)
            total += member.size
        if total > 2 * 1024**3:
            raise ValueError("Release exceeds unpacked size limit")
        manifest = json.loads(archive.extractfile("release.json").read())
        version(manifest["version"])
        if manifest.get("schema") != 1 or manifest["version"] != expected or manifest.get("target") != TARGET:
            raise ValueError("Release identity/target mismatch")
        version(manifest["upstream_tag"])
        if manifest['version'] != manifest['upstream_tag']:
            raise ValueError('Project version must match the pinned upstream version')
        if not re.fullmatch(r'[0-9a-f]{64}', manifest.get('upstream_sha256', '')):
            raise ValueError('Pinned upstream archive checksum missing')
        files = manifest["files"]
        if set(files) != REQUIRED:
            raise ValueError("Release must contain only our tools, patches and splash assets; upstream source/binaries are forbidden")
        regular = {m.name for m in members if m.isfile()} - {"release.json"}
        if set(files) != regular:
            raise ValueError("Manifest does not cover every release file")
        for name, checksum in files.items():
            safe_name(name)
            if not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise ValueError("Invalid checksum in release manifest")
            if hashlib.sha256(archive.extractfile(name).read()).hexdigest() != checksum:
                raise ValueError("Release file checksum mismatch: " + name)
        # Extract regular files ourselves; never honor archive ownership or modes.
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                target.chmod(0o644)
    return manifest


def download(assets, directory, tag):
    checksums = fetch(assets["SHA256SUMS"]["browser_download_url"]).decode()
    matches = re.findall(r"^([0-9a-f]{64})  " + re.escape(ASSET) + r"$", checksums, re.M)
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous bundle checksum")
    bundle = directory / ASSET
    bundle.write_bytes(fetch(assets[ASSET]["browser_download_url"]))
    if hashlib.sha256(bundle.read_bytes()).hexdigest() != matches[0]:
        raise ValueError("Downloaded bundle checksum mismatch")
    payload = directory / "payload"
    payload.mkdir()
    unpack(bundle, payload, tag)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("install", "update"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Check our release version; do not install")
    mode.add_argument("--reinstall", action="store_true", help="Rebuild the installed project release")
    mode.add_argument("--cleanup", action="store_true")
    parser.add_argument("tag", nargs="?", help="Our project tag, never an upstream version")
    parser.add_argument("--candidate", metavar="TAG", help="Explicitly select a published project prerelease for this invocation only")
    args = parser.parse_args()
    if args.candidate and (args.operation != "update" or args.tag or args.cleanup):
        parser.error("Use update --candidate TAG, optionally with --check or --reinstall")
    if args.cleanup and (args.operation != "update" or args.tag):
        parser.error("Use update --cleanup without a tag")
    def selected_release():
        return find_release(args.candidate, candidate=True) if args.candidate else find_release(args.tag)
    if args.check:
        release, _ = selected_release()
        current = installed_version()
        print(f"Installed pi-switch-dock: {current or 'not installed'}")
        print(f"{'Candidate' if args.candidate else 'Published'} pi-switch-dock: {release['tag_name']}")
        print("Update available." if newer(release["tag_name"], current) else "No newer project release.")
        return
    if os.geteuid() != 0:
        parser.error("Run with sudo")
    import fcntl
    with open("/run/lock/pi-switch-dock-update.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another install, update or rollback is running")
        if args.cleanup:
            subprocess.run(["bash", str(Path(__file__).with_name("deploy.sh")), "--cleanup"], check=True,
                           env={**os.environ, "PI_SWITCH_DOCK_RELEASE_LOCKED": "1"})
            return
        release, assets = selected_release()
        tag = release["tag_name"]
        current = installed_version()
        if current and version(tag) < version(current):
            raise ValueError("Refusing a project downgrade; use pi-switch-dock-rollback")
        if args.operation == "update" and current == tag and not args.reinstall:
            print(f"pi-switch-dock {tag} is already installed. Nothing to update.")
            return
        print(f"Downloading pi-switch-dock {tag}", flush=True)
        with tempfile.TemporaryDirectory(prefix="pi-switch-dock-release-") as tmp:
            payload = download(assets, Path(tmp), tag)
            script = "setup.sh" if args.operation == "install" else "deploy.sh"
            # The parent holds the maintenance lock for download AND activation.
            subprocess.run(["bash", str(payload / script)], check=True,
                           env={**os.environ, "PI_SWITCH_DOCK_RELEASE_LOCKED": "1"})


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as error:
        raise SystemExit("pi-switch-dock: " + str(error))
