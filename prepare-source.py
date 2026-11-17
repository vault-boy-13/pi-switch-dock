#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Download exactly the source pinned by our release, never upstream latest."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import urllib.request

from release_client import safe_name, version


def prepare(manifest_path, destination):
    manifest = json.loads(manifest_path.read_text())
    tag = manifest['upstream_tag']
    version(tag)
    if tag != manifest['version']:
        raise ValueError('Project and upstream versions must match')
    url = f'https://github.com/TomasUribe/switch-frame-tap/archive/refs/tags/{tag}.tar.gz'
    archive_path = destination.parent / 'upstream.tar.gz'
    digest = hashlib.sha256()
    print(f'Downloading pinned Switch Frame Tap {tag}', flush=True)
    with urllib.request.urlopen(url, timeout=60) as response, archive_path.open('wb') as output:
        for chunk in iter(lambda: response.read(1024 * 1024), b''):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != manifest['upstream_sha256']:
        raise ValueError('Upstream source checksum mismatch; current receiver unchanged')
    with tarfile.open(archive_path, 'r:gz') as archive:
        entries = []
        names = set()
        total = 0
        for member in archive.getmembers():
            name = member.name.rstrip('/')
            safe_name(name)
            if name in names or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe upstream archive entry')
            names.add(name)
            parts = PurePosixPath(name).parts
            if parts[0] != 'switch-frame-tap-' + tag[1:]:
                raise ValueError('Unexpected upstream archive root')
            total += member.size
            if len(parts) > 1:
                entries.append((member, destination.joinpath(*parts[1:])))
        if total > 2 * 1024**3:
            raise ValueError('Upstream source exceeds size limit')
        for member, target in entries:
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    for name in ('common/sft_version.h', 'tools/raw-recv/raw-view.c', 'tools/raw-recv/Makefile'):
        if not (destination / name).is_file():
            raise ValueError('Upstream source missing required file: ' + name)


if __name__ == '__main__':
    prepare(Path(sys.argv[1]), Path(sys.argv[2]))
