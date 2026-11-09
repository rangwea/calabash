import json
import tomllib
import unittest
from pathlib import Path

from core.app_info import APP_NAME, APP_VERSION

ROOT = Path(__file__).resolve().parents[1]

class AppInfoTests(unittest.TestCase):
    def test_release_metadata_matches_package_source(self):
        package = json.loads((ROOT / 'package.json').read_text())
        lock = json.loads((ROOT / 'package-lock.json').read_text())
        python = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
        plugin = json.loads((ROOT / 'electron/workspace/package.json').read_text())
        self.assertEqual('Calabash', APP_NAME)
        self.assertEqual(APP_NAME, package['productName'])
        for version in [package['version'],lock['version'],lock['packages']['']['version'],python['version'],plugin['version']]:
            self.assertEqual(APP_VERSION, version)

    def test_readme_version_badges_match_app_version(self):
        for name in ('README.md', 'README.zh-CN.md'):
            with self.subTest(readme=name):
                self.assertIn(
                    f'badge/version-v{APP_VERSION}-',
                    (ROOT / name).read_text(),
                    name,
                )
