import ast
import tempfile
import unittest
from pathlib import Path
from string import Formatter
from unittest.mock import patch

from core import i18n


class I18nTests(unittest.TestCase):
    def test_language_persistence_and_fallback(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(i18n, "app_dir", return_value=Path(directory)):
            self.assertEqual("zh-CN", i18n.language())
            self.assertEqual("设置", i18n.t("设置"))
            i18n.set_language("en")
            self.assertEqual("Settings", i18n.t("设置"))
            self.assertEqual("2 tools · 1 projects", i18n.t("{tools} 个工具 · {projects} 个项目", tools=2, projects=1))
            self.assertEqual("user content", i18n.t("user content"))
            with self.assertRaises(ValueError):
                i18n.set_language("invalid")
            (Path(directory) / "language.json").write_text("invalid json")
            self.assertEqual("zh-CN", i18n.language())

    def test_catalog_placeholders_and_coverage(self):
        catalog = i18n._english()
        def fields(value):
            return {name for _, name, _, _ in Formatter().parse(value) if name}
        for source, translated in catalog.items():
            self.assertEqual(fields(source), fields(translated), source)
        root = Path(__file__).resolve().parents[1]
        for folder in ("component", "ui", "service"):
            for path in (root / folder).rglob("*.py"):
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t" and node.args and isinstance(node.args[0], ast.Constant):
                        self.assertIn(node.args[0].value, catalog, str(path))
