import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.tools.tool_jobs import ToolJobs
from service.files.tool_outputs import ToolOutputs


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch("service.files.tool_outputs.app_dir", return_value=Path(self.temp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        patcher = patch("service.chat.ai_chat.app_dir", return_value=Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unique_and_failed_writes(self):
        outputs = ToolOutputs()
        first = outputs.write("report.txt", lambda path: path.write_text("one"))
        second = outputs.write("report.txt", lambda path: path.write_text("two"))
        self.assertEqual(outputs.path(first).read_text(), "one")
        self.assertEqual(outputs.path(second).name, "report (1).txt")

        def fail(path):
            path.write_text("partial")
            raise ValueError("failed")

        with self.assertRaises(ValueError):
            outputs.write("failed.txt", fail)
        self.assertEqual(len(outputs.files()), 2)
        self.assertFalse(list(outputs.directory.glob(".*")))

    def test_invalid_names_and_tampering(self):
        outputs = ToolOutputs()
        for name in ["../secret", "/tmp/out", "..", "", "a\\b"]:
            with self.assertRaises(ValueError):
                outputs.write(name, lambda path: path.touch())
        key = outputs.write("report.txt", lambda path: path.write_text("ok"))
        path = outputs.path(key)
        path.unlink()
        path.symlink_to(Path(self.temp.name))
        with self.assertRaises(ValueError):
            outputs.path(key)

    def test_no_cross_run_access(self):
        a, b = ToolOutputs(), ToolOutputs()
        key = a.write("report.txt", lambda path: path.write_text("ok"))
        with self.assertRaises(KeyError):
            b.path(key)

    def test_ticket_contains_only_authorized_output(self):
        outputs = ToolOutputs()
        key = outputs.write("report.txt", lambda path: path.write_text("ok"))
        with patch.dict(os.environ, {"CALABASH_SELECTION_DIR": self.temp.name}):
            token = outputs.save_ticket(key)
        ticket = Path(self.temp.name) / f"output-{token}.json"
        data = json.loads(ticket.read_text())
        self.assertEqual(data["path"], str(outputs.path(key)))
        self.assertEqual(data["size"], 2)
        self.assertEqual(ticket.stat().st_mode & 0o777, 0o600)

    def test_excel_merge_export_preserves_inputs(self):
        import pandas as pd

        sources = [Path(self.temp.name) / f"source-{i}.xlsx" for i in range(2)]
        for index, source in enumerate(sources):
            pd.DataFrame({"team": ["A", "B"], "amount": [index + 1, 99]}).to_excel(source, index=False)
        originals = [source.read_bytes() for source in sources]
        merged = pd.concat([pd.read_excel(source) for source in sources], ignore_index=True)
        filtered = merged[merged["team"] == "A"]
        outputs = ToolOutputs()
        key = outputs.write("merged.xlsx", lambda path: filtered.to_excel(path, index=False))
        exported = pd.read_excel(outputs.path(key))
        self.assertEqual(exported["amount"].tolist(), [1, 2])
        self.assertEqual([source.read_bytes() for source in sources], originals)


class JobTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_only_retry(self):
        jobs = ToolJobs([1, 2, 3])
        calls = []

        async def handler(value):
            calls.append(value)
            if value == 2 and calls.count(2) == 1:
                raise ValueError("bad")
            return value * 2

        await jobs.run(handler)
        self.assertEqual([j.status for j in jobs.jobs], ["succeeded", "failed", "succeeded"])
        await jobs.run(handler, retry_failed=True)
        self.assertEqual(calls, [1, 2, 3, 2])
        self.assertTrue(all(j.status == "succeeded" for j in jobs.jobs))

    async def test_cancel_waits_for_current_item(self):
        jobs = ToolJobs([1, 2, 3])
        started, release = asyncio.Event(), asyncio.Event()

        async def handler(value):
            started.set()
            await release.wait()
            return value

        task = asyncio.create_task(jobs.run(handler))
        await started.wait()
        jobs.cancel()
        self.assertTrue(jobs.running)
        self.assertEqual(jobs.jobs[0].status, "running")
        release.set()
        await task
        self.assertEqual([j.status for j in jobs.jobs], ["succeeded", "cancelled", "cancelled"])
        self.assertFalse(jobs.running)
