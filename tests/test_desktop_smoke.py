"""桌面后端启动参数和本地运行契约测试。"""

import json
import tomllib
import unittest
from pathlib import Path

from backend.desktop_server import _find_free_port, _prepare_runtime


class DesktopSmokeTest(unittest.TestCase):
    def test_generated_application_name_is_calabash(self):
        root = Path(__file__).resolve().parents[1] / "src-tauri"
        config = json.loads((root / "tauri.conf.json").read_text())
        cargo = tomllib.loads((root / "Cargo.toml").read_text())
        self.assertEqual("Calabash", config["productName"])
        self.assertEqual("Calabash", config["mainBinaryName"])
        self.assertEqual("Calabash", config["app"]["windows"][0]["title"])
        self.assertEqual([{"name": "Calabash", "path": "src/main.rs"}], cargo["bin"])
        self.assertEqual("local.calabash.desktop", config["identifier"])

    def test_runtime_uses_localhost_and_random_port(self):
        first = _prepare_runtime(None)
        second = _prepare_runtime(None)

        self.assertEqual(first[0], "127.0.0.1")
        self.assertEqual(second[0], "127.0.0.1")
        self.assertNotEqual(first[1], second[1])
        self.assertGreater(first[1], 0)
        self.assertGreater(second[1], 0)

    def test_free_port_is_positive(self):
        self.assertGreater(_find_free_port(), 0)


if __name__ == "__main__":
    unittest.main()
