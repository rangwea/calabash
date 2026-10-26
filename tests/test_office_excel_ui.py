import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nicegui import core, ui
from openpyxl import Workbook, load_workbook

from service.chat import ai_chat
from service.files import tool_inputs
from service.files import tool_outputs

FIXTURE = Path(__file__).parent / "fixtures/office_excel_tool.py"


class ExcelInteractionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.container = ui.column()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for module in (ai_chat, tool_outputs):
            patcher = patch.object(module, "app_dir", return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.source = self.root / "office.xlsx"
        book = Workbook()
        book.active.title = "Sales"
        for row in [("Team", "Amount"), ("A", 10), ("B", 20), ("A", 5)]:
            book.active.append(row)
        book.create_sheet("Other").append(["Department", "Hours"])
        book["Other"].append(["Support", 8])
        book.save(self.source)
        book.close()
        spec = importlib.util.spec_from_file_location("office_fixture", FIXTURE)
        self.fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.fixture)

    async def test_workbook_fields_filter_chart_export_and_failure_recovery(self):
        async def io_bound(function, *args):
            return await asyncio.to_thread(function, *args)

        with patch.object(core, "loop", asyncio.get_running_loop()), self.container, patch.object(tool_inputs, "current_inputs", return_value=[{"path": str(self.source)}]), patch.object(self.fixture.run, "io_bound", io_bound), patch.object(ui.context.client, "calabash_output_owner", ("tool:acceptance/excel", None), create=True), patch.object(self.fixture.logger, "exception"):
            self.fixture.main()
            buttons = {element.text: element for element in self.container.descendants() if isinstance(element, ui.button)}
            fields = {element._props.get("label"): element for element in self.container.descendants() if isinstance(element, (ui.input, ui.select))}
            chart = next(element for element in self.container.descendants() if isinstance(element, ui.echart))
            table = next(element for element in self.container.descendants() if isinstance(element, ui.table))

            async def click(text):
                next(iter(buttons[text]._event_listeners.values())).handler(None)
                for _ in range(200):
                    await asyncio.sleep(0.01)
                    if buttons["读取工作簿"].enabled:
                        return
                self.fail("Fixture callback did not finish")

            self.assertFalse(buttons["汇总"].enabled)
            await click("读取工作簿")
            self.assertEqual(["Sales", "Other"], fields["工作表"].options)
            await click("汇总")
            self.assertEqual([{"group": "A", "total": 15}, {"group": "B", "total": 20}], table.rows)
            self.assertEqual([15, 20], chart.options["series"][0]["data"])
            fields["分组包含"].set_value("A")
            await asyncio.sleep(0)
            self.assertFalse(buttons["导出结果"].enabled)
            await click("汇总")
            self.assertEqual([{"group": "A", "total": 15}], table.rows)
            await click("导出结果")
            outputs = tool_outputs.ToolOutputs(owner=("tool:acceptance/excel", None))
            report = load_workbook(outputs.path(outputs.files()[0]["id"]), read_only=True)
            try:
                self.assertEqual([("Group", "Total"), ("A", 15)], list(report.active.values))
            finally:
                report.close()
            fields["工作表"].set_value("Other")
            await asyncio.sleep(0)
            self.assertEqual(["Department", "Hours"], fields["数值字段"].options)
            fields["分组包含"].set_value("")
            await click("汇总")
            self.assertEqual([{"group": "Support", "total": 8}], table.rows)
            fields["数值字段"].set_value("Department")
            await click("汇总")
            self.assertEqual([], table.rows)
            self.assertFalse(buttons["导出结果"].enabled)
            self.assertTrue(buttons["读取工作簿"].enabled)

    def test_export_does_not_interpret_group_labels_as_formulas(self):
        path = self.root / "formula.xlsx"
        self.fixture.write_report(path, (("=1+1", 2),))
        book = load_workbook(path, read_only=True)
        try:
            self.assertEqual("s", book.active["A2"].data_type)
        finally:
            book.close()
