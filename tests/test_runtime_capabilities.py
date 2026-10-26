import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from core import runtime_capabilities as runtime
from scripts import build_desktop_sidecar as build


class RuntimeCapabilitiesTests(unittest.TestCase):
    def test_declared_libraries_and_optional_packs_are_separate(self):
        data = runtime.catalog()
        dependencies = tomllib.loads((build.ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
        for item in data["libraries"]:
            if item["module"] == "numpy":
                continue  # pandas requires numpy; not a separate direct dependency.
            self.assertTrue(any(value.casefold().startswith(item["distribution"].casefold() + ">=") for value in dependencies), item)
            self.assertIn(item["module"], runtime.agent_guidance())
        self.assertEqual({"media.ffmpeg", "document.ocr"}, {item["id"] for item in data["optional_packs"]})
        self.assertEqual({"media.ffmpeg": "local_zip", "document.ocr": "planned"},
                         {item["id"]: item["status"] for item in data["optional_packs"]})

    def test_real_offline_library_roundtrips(self):
        result = runtime.check_runtime()
        self.assertTrue(result["ok"], result)
        self.assertEqual(["office_roundtrip", "image_roundtrip", "pdf_generation", "pdf_rendering"], result["checks"])

    def test_missing_library_fails_closed(self):
        original = runtime.import_module

        def missing(name):
            if name == "PIL":
                raise ImportError("missing")
            return original(name)

        with patch.object(runtime, "import_module", side_effect=missing):
            result = runtime.check_runtime()
        self.assertFalse(result["ok"])
        self.assertEqual("ImportError", result["errors"]["PIL"])

    def test_build_collects_resources_and_checks_frozen_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = []

            def execute(command):
                commands.append(command.copy())
                if command[0] == "uv":
                    (root / "calabash-backend").write_bytes(b"synthetic executable")

            with patch.object(build, "BIN_DIR", root), patch.object(build, "PYINSTALLER_WORK_DIR", root / "work"), patch.object(build, "_host_triple", return_value="synthetic"), patch.object(build, "_run", side_effect=execute), patch.object(build.os, "name", "posix"):
                build.main()
            command = commands[0]
            for module in ("PIL", "reportlab", "pypdfium2", "pypdfium2_raw"):
                self.assertTrue(any(command[index:index + 2] == ["--collect-all", module] for index in range(len(command))))
            self.assertEqual("--check-runtime", commands[1][-1])

    def test_selfcheck_cli_exits_without_starting_server(self):
        result = subprocess.run([sys.executable, "-m", "backend.desktop_server", "--check-runtime"], cwd=build.ROOT, capture_output=True, text=True, timeout=60, check=True)
        self.assertTrue(json.loads(result.stdout)["ok"])
        self.assertNotIn("CALABASH_READY", result.stdout)
