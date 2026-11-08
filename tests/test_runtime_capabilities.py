import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from core import runtime_capabilities as runtime

ROOT = Path(__file__).resolve().parents[1]


class RuntimeCapabilitiesTests(unittest.TestCase):
    def test_declared_libraries_and_optional_packs_are_separate(self):
        data = runtime.catalog()
        dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
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
