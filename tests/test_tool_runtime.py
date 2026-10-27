import tempfile
import unittest
from pathlib import Path

from service.tools.preview_service import save_preview
from service.tools.tool_runtime import (
    ToolEntryPointError,
    load_tool_entrypoint,
    validate_tool_entrypoint,
)


class ToolRuntimeTest(unittest.TestCase):
    def test_known_invalid_component_apis_are_rejected_without_execution(self):
        for source, hint in [
            ('from component.tool_results import ToolResults as Results\ndef main():\n    results = Results()\n    results.mount()\n', 'remove mount()'),
            ('from nicegui import ui\ndef main():\n    chart = ui.echart({}).classes("w-full")\n    chart.options = {}\n', 'read-only'),
        ]:
            with self.subTest(source=source), self.assertRaisesRegex(ToolEntryPointError, hint.replace('(', r'\(').replace(')', r'\)')):
                validate_tool_entrypoint(source)

    def test_valid_component_updates_and_unrelated_mount_are_allowed(self):
        validate_tool_entrypoint('from component.tool_results import ToolResults\nfrom nicegui import ui\ndef main():\n    results = ToolResults()\n    results.refresh()\n    chart = ui.echart({})\n    chart.options.update({})\n    chart.update()\n    other.mount()\n')

    def test_validates_sync_and_async_main(self):
        self.assertFalse(validate_tool_entrypoint("def main():\n    pass\n"))
        self.assertTrue(validate_tool_entrypoint("async def main():\n    pass\n"))

    def test_rejects_nested_or_missing_main(self):
        with self.assertRaises(ToolEntryPointError):
            validate_tool_entrypoint("if True:\n    def main():\n        pass\n")

    def test_loads_callable_main(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tool.py"
            path.write_text("def main():\n    return 42\n", encoding="utf-8")

            main, is_async = load_tool_entrypoint("runtime_test_tool", str(path))

            self.assertFalse(is_async)
            self.assertEqual(main(), 42)

    def test_preview_rejects_content_without_main(self):
        result = save_preview(
            preview_key="missing-main-test",
            content="print('legacy')\n",
            preview_type="temporary",
            url="/preview/missing-main-test",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["code"], "missing_main")
        self.assertEqual(result["next_action"], "add_main")


if __name__ == "__main__":
    unittest.main()
