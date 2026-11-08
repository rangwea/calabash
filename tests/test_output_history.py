import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from service.files import output_history, tool_outputs


class OutputHistoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for module in (output_history, tool_outputs):
            patcher = patch.object(module, "app_dir", return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.owner = ("tool:demo/history", None)

    def test_history_survives_new_instance_and_worker_thread(self):
        original = tool_outputs.ToolOutputs(owner=self.owner)
        with ThreadPoolExecutor(max_workers=1) as executor:
            file_id = executor.submit(original.write, "report.txt", lambda path: path.write_text("one")).result()
        restored = tool_outputs.ToolOutputs(owner=self.owner)
        self.assertNotEqual(original.id, restored.id)
        self.assertEqual([file_id], [row["id"] for row in restored.files()])
        self.assertEqual("one", restored.path(file_id).read_text())
        second_id = restored.write("report.txt", lambda path: path.write_text("two"))
        self.assertEqual(2, len(restored.files()))
        self.assertNotEqual(restored.path(file_id), restored.path(second_id))
        self.assertEqual("one", restored.path(file_id).read_text())

    def test_tool_and_chat_scopes_are_isolated(self):
        writer = tool_outputs.ToolOutputs(owner=(self.owner[0], "one"))
        file_id = writer.write("report.txt", lambda path: path.write_text("one"))
        for owner in [self.owner, (self.owner[0], "two"), ("tool:demo/other", "one")]:
            other = tool_outputs.ToolOutputs(owner=owner)
            self.assertEqual([], other.files())
            with self.assertRaises(KeyError):
                other.path(file_id)

    def test_new_batch_retains_previous_results_and_inflight_owner(self):
        writer = tool_outputs.ToolOutputs(owner=self.owner)
        first_run = writer.id

        def export(path):
            writer.start_run()
            path.write_text("old run finishes")

        old_id = writer.write("report.txt", export)
        new_id = writer.write("report.txt", lambda path: path.write_text("new run"))
        records = {row["id"]: row for row in writer.files()}
        self.assertEqual(first_run, records[old_id]["run_id"])
        self.assertEqual(writer.id, records[new_id]["run_id"])
        self.assertNotEqual(first_run, writer.id)
        self.assertEqual("old run finishes", writer.path(old_id).read_text())

    def test_missing_changed_and_symlink_files_do_not_break_siblings(self):
        writer = tool_outputs.ToolOutputs(owner=self.owner)
        ids = [writer.write(f"report-{index}.txt", lambda path: path.write_text("one")) for index in range(4)]
        writer.path(ids[0]).unlink()
        writer.path(ids[1]).write_text("changed")
        link = writer.path(ids[2])
        link.unlink()
        link.symlink_to(self.root / "outside")
        restored = tool_outputs.ToolOutputs(owner=self.owner)
        rows = {row["id"]: row for row in restored.files()}
        self.assertEqual(4, len(rows))
        self.assertTrue(rows[ids[3]]["available"])
        for file_id in ids[:3]:
            self.assertFalse(rows[file_id]["available"])
            with self.assertRaises((OSError, ValueError)):
                restored.path(file_id)
