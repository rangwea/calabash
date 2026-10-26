"""Office scenarios using real parsers and temporary, synthetic user files."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

from service.chat import ai_chat
from service.files import conversation_files
from service.files import file_readers
from service.files import tool_inputs
from service.files import tool_outputs
from service.files.tool_input_selection import ToolInputSelection
from service.tools.tool_jobs import ToolJobs


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
        token = tool_inputs.create("office", "office-preview", messages, tool_key="tool:demo/office")
        return item, token

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
        item, token = self.attach(source)
        structure = await file_readers.read_attachment("office", item["id"])
        self.assertEqual(["Sales", "Notes"], [sheet["name"] for sheet in structure["sheets"]])
        sample = await file_readers.read_attachment("office", item["id"], sheet="Sales", limit=2)
        self.assertTrue(sample["truncated"])
        selection = ToolInputSelection(tool_inputs.resolve(token, "office-preview"), context=(token, "office-preview"))
        paths = selection.freeze()
        owner = tool_inputs.owner(token, "office-preview")
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

        try:
            key = await asyncio.to_thread(outputs.write, "summary.xlsx", write_report)
        finally:
            selection.set_locked(False)
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

    async def test_failed_batch_retries_original_inputs_and_restores_results(self):
        first, broken, later = [self.root / name for name in ("first.txt", "broken.txt", "later.txt")]
        first.write_text("first")
        broken.write_bytes(b"\xff")
        later.write_text("later")
        originals = first.read_bytes(), later.read_bytes()
        selection = ToolInputSelection([])
        selection.add([first, broken, first])
        jobs = ToolJobs(selection.freeze())
        outputs = tool_outputs.ToolOutputs(owner=("tool:demo/batch", None))
        calls = []

        async def handle(path):
            self.assertTrue(selection.locked)
            self.assertFalse(selection.clear())
            calls.append(path)

            def write(destination):
                destination.write_text(Path(path).read_text(encoding="utf-8").upper())

            return await asyncio.to_thread(outputs.write, Path(path).name, write)

        def changed():
            selection.set_locked(jobs.running)

        await jobs.run(handle, changed=changed)
        self.assertEqual(["succeeded", "failed"], [job.status for job in jobs.jobs])
        selection.clear()
        selection.add([later])
        broken.write_text("repaired")
        await jobs.run(handle, retry_failed=True, changed=changed)
        self.assertEqual([str(first), str(broken), str(broken)], calls)
        self.assertEqual([str(later)], selection.paths())
        restored = tool_outputs.ToolOutputs(owner=outputs.owner)
        self.assertEqual(2, len(restored.files()))
        self.assertEqual({outputs.id}, {row["run_id"] for row in restored.files()})
        self.assertEqual({"FIRST", "REPAIRED"}, {restored.path(row["id"]).read_text() for row in restored.files()})
        self.assertEqual(originals, (first.read_bytes(), later.read_bytes()))
