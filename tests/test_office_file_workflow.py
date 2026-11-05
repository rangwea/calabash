"""Office scenarios using real parsers and temporary, synthetic user files."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

from service.chat import ai_chat
from service.files import conversation_files, file_readers, tool_outputs


class OfficeWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for module in (ai_chat, tool_outputs):
            patcher = patch.object(module, "app_dir", return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)

    def attach(self, path):
        item = conversation_files.register("office", path)
        messages = [{"role": "user", "content": "Analyze by team", "attachments": [item["id"]]}]
        ai_chat.save_chat("office", messages)
        return item

    async def test_excel_structure_full_data_export_and_restored_history(self):
        source = self.root / "sales.xlsx"
        workbook = Workbook()
        workbook.active.title = "Sales"
        workbook.active.append(["Team", "Amount"])
        for _ in range(105):
            workbook.active.append(["A", 10])
        workbook.active.append(["B", 20])
        workbook.create_sheet("Notes").append(["Synthetic fixture"])
        workbook.save(source)
        workbook.close()
        original = source.read_bytes()
        item = self.attach(source)
        structure = await file_readers.read_attachment("office", item["id"])
        self.assertEqual(["Sales", "Notes"], [sheet["name"] for sheet in structure["sheets"]])
        sample = await file_readers.read_attachment("office", item["id"], sheet="Sales", limit=2)
        self.assertTrue(sample["truncated"])
        paths = [str(source)]
        owner = ("tool:demo/office", "office")
        outputs = tool_outputs.ToolOutputs(owner=owner)

        def write_report(destination):
            incoming = load_workbook(paths[0], read_only=True, data_only=True)
            try:
                totals = {}
                for team, amount in incoming["Sales"].iter_rows(min_row=2, values_only=True):
                    totals[team] = totals.get(team, 0) + amount
                report = Workbook()
                report.active.append(["Team", "Total"])
                for team, amount in sorted(totals.items()):
                    report.active.append([team, amount])
                report.save(destination)
                report.close()
            finally:
                incoming.close()

        key = await asyncio.to_thread(outputs.write, "summary.xlsx", write_report)
        restored = tool_outputs.ToolOutputs(owner=owner)
        report = load_workbook(restored.path(key), read_only=True, data_only=True)
        try:
            self.assertEqual([("Team", "Total"), ("A", 1050), ("B", 20)], list(report.active.values))
        finally:
            report.close()
        self.assertEqual(original, source.read_bytes())
        self.assertTrue(restored.files()[0]["available"])
        with self.assertRaises(KeyError):
            tool_outputs.ToolOutputs(owner=(owner[0], None)).path(key)
