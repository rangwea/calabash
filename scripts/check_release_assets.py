"""Require a complete version-matched release; checksum only the expected installers."""
import hashlib
import json
import os
import sys
from pathlib import Path


def verify(directory):
    version = json.loads((Path(__file__).resolve().parents[1] / 'package.json').read_text())['version']
    if os.environ.get('GITHUB_REF_NAME') != f'v{version}':
        raise ValueError('Release tag differs from package.json')
    names = [f'Calabash-{version}-macos-arm64.dmg', f'Calabash-{version}-macos-x64.dmg', f'Calabash-{version}-windows-x64-setup.exe']
    actual = sorted(path.name for path in directory.iterdir() if path.name != 'SHA256SUMS.txt')
    if actual != sorted(names):
        raise ValueError('Release requires exactly three version-matched native installers')
    lines = []
    for name in names:
        path = directory / name
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            raise ValueError('Invalid installer artifact')
        with path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        lines.append(f'{digest}  {name}\n')
    (directory / 'SHA256SUMS.txt').write_text(''.join(lines), encoding='utf-8')


if __name__ == '__main__':
    verify(Path(sys.argv[1]))
