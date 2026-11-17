#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Package only our adaptation tools and patches after local validation."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

from release_client import ASSET, REQUIRED, TARGET, unpack, version

ROOT = Path(__file__).resolve().parent


def package(spec_path, output):
    spec = json.loads(spec_path.read_text())
    tag = spec['version']
    version(tag)
    if tag != spec['upstream_tag']:
        raise ValueError('Our release version must match upstream')
    # A closed file list prevents accidentally publishing author code/binaries.
    manifest = {**spec, 'schema': 1, 'target': TARGET,
                'files': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in sorted(REQUIRED)}}
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dock-tools-package-') as tmp:
        release_json = Path(tmp) / 'release.json'
        release_json.write_text(json.dumps(manifest, indent=2) + '\n')
        archive_path = output / ASSET
        with tarfile.open(archive_path, 'w:gz') as archive:
            archive.add(release_json, arcname='release.json')
            for name in sorted(REQUIRED):
                archive.add(ROOT / name, arcname=name, recursive=False)
        unpack(archive_path, Path(tmp) / 'verified', tag)
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        (output / 'SHA256SUMS').write_text(f'{digest}  {ASSET}\n', newline='\n')
    print(f'Prepared pi-switch-dock {tag}: {archive_path}')
    print('No upstream source or executable included. Publication is a separate manual step.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, default=ROOT / 'release-spec.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    package(args.spec.resolve(), args.output.resolve())
