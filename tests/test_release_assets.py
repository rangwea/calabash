"""Release gates reject incomplete, unexpected or mismatched installer sets."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_release_assets import verify


class ReleaseAssetsTests(unittest.TestCase):
    def test_exact_native_installers_produce_checksums(self):
        version = json.loads((Path(__file__).resolve().parents[1] / 'package.json').read_text())['version']
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'GITHUB_REF_NAME': 'v' + version}):
            root = Path(temp)
            names = [f'Calabash-{version}-macos-arm64.dmg', f'Calabash-{version}-macos-x64.dmg', f'Calabash-{version}-windows-x64-setup.exe']
            for name in names:
                (root / name).write_bytes(b'synthetic installer')
            verify(root)
            self.assertEqual(3, len((root / 'SHA256SUMS.txt').read_text().splitlines()))
            verify(root)  # Retrying a draft checksum step is safe.
            (root / names[0]).unlink()
            with self.assertRaises(ValueError):
                verify(root)

    def test_rejects_mismatched_tag(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'GITHUB_REF_NAME': 'v0.0.0'}), self.assertRaises(ValueError):
            verify(Path(temp))
