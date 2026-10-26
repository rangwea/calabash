import asyncio
import json
import tomllib
import unittest
from pathlib import Path

from core.app_info import APP_NAME, APP_VERSION
from api.health_api import health_info
from ui.settings import _collect_diagnostics

ROOT = Path(__file__).resolve().parents[1]


class AppInfoTests(unittest.TestCase):
    def test_release_metadata_matches_package_source(self):
        package = json.loads((ROOT / "package.json").read_text())
        lock = json.loads((ROOT / "package-lock.json").read_text())
        python = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        cargo = tomllib.loads((ROOT / "src-tauri/Cargo.toml").read_text())["package"]
        tauri = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text())
        self.assertEqual("Calabash", APP_NAME)
        self.assertEqual(APP_NAME, package["productName"])
        self.assertEqual(APP_NAME, tauri["productName"])
        self.assertEqual(
            ROOT / "package.json", (ROOT / "src-tauri" / tauri["version"]).resolve()
        )
        for version in (
            package["version"],
            lock["version"],
            lock["packages"][""]["version"],
            python["version"],
            cargo["version"],
        ):
            self.assertEqual(APP_VERSION, version)

    def test_health_and_diagnostics_use_shared_version(self):
        health = asyncio.run(health_info())
        self.assertEqual(APP_VERSION, health["version"])
        self.assertEqual(APP_NAME, health["name"])
        self.assertEqual(APP_VERSION, _collect_diagnostics(0, 0)["应用版本"])
