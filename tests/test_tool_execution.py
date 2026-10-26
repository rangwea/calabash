import asyncio
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from nicegui import core, ui

from component.tool_results import ToolJobStatus
from service.tools import tool_activity
from service.tools.tool_jobs import ToolJobs, ToolTask


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.container = ui.column()

    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        env = patch.dict(os.environ, {"CALABASH_SELECTION_DIR": self.directory.name})
        env.start()
        self.addCleanup(env.stop)

    async def test_progress_and_duplicate_owner_lock_until_current_finishes(self):
        jobs = ToolJobs([1, 2], owner="tool:progress")
        entered, release = asyncio.Event(), asyncio.Event()

        async def handler(value):
            jobs.report_progress(0.5)
            entered.set()
            await release.wait()
            return value

        task = asyncio.create_task(jobs.run(handler))
        await entered.wait()
        try:
            self.assertEqual("running", jobs.status)
            self.assertEqual(0.25, jobs.progress)
            jobs.cancel()
            self.assertEqual("cancelling", jobs.status)
            self.assertTrue(jobs.running)
            self.assertEqual(1, json.loads((self.root / "active-jobs.json").read_text())["active"])
            with self.assertRaises(RuntimeError):
                await ToolJobs([3], owner="tool:progress").run(handler)
        finally:
            release.set()
            await task
        self.assertEqual("cancelled", jobs.status)
        self.assertEqual(0.5, jobs.progress)
        self.assertEqual(["succeeded", "cancelled"], [job.status for job in jobs.jobs])
        self.assertEqual(0, tool_activity.active_count())
        self.assertEqual(0, json.loads((self.root / "active-jobs.json").read_text())["active"])

    async def test_external_task_cancellation_waits_for_real_writer(self):
        jobs = ToolJobs([1, 2])
        entered, release = threading.Event(), threading.Event()
        output = self.root / "completed.txt"

        def writer():
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Test writer not released")
            output.write_text("complete")

        async def handler(_):
            await asyncio.to_thread(writer)

        task = asyncio.create_task(jobs.run(handler))
        await asyncio.to_thread(entered.wait, 1)
        try:
            task.cancel()
            for _ in range(5):
                await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertTrue(jobs.running)
            self.assertEqual("cancelling", jobs.status)
            self.assertEqual(1, tool_activity.active_count())
        finally:
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual("complete", output.read_text())
        self.assertEqual(["succeeded", "cancelled"], [job.status for job in jobs.jobs])
        self.assertEqual(0, tool_activity.active_count())

    async def test_native_stop_request_waits_and_rejects_new_work(self):
        entered, release = asyncio.Event(), asyncio.Event()
        jobs = ToolTask()

        async def operation():
            entered.set()
            await release.wait()
            return "saved"

        task = asyncio.create_task(jobs.run(operation))
        await entered.wait()
        try:
            (self.root / "stop-jobs").touch()
            tool_activity.check_stop_request()
            self.assertEqual("cancelling", jobs.status)
            self.assertTrue(jobs.running)
            with self.assertRaises(RuntimeError):
                await ToolTask().run(operation)
        finally:
            release.set()
            await task
        self.assertEqual("saved", jobs.result)
        self.assertEqual("cancelled", jobs.status)
        self.assertEqual(0, json.loads((self.root / "active-jobs.json").read_text())["active"])

    async def test_status_freezes_controls_and_ignores_duplicate_submit(self):
        container = self.container
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        with patch.object(core, "loop", asyncio.get_running_loop()), container:
            control = ui.input("Name")
            disabled = ui.button("Already disabled")
            disabled.disable()
            status = ToolJobStatus(ToolTask(), controls=(control, disabled))

            async def handler():
                calls.append(True)
                entered.set()
                await release.wait()
                return "result"

            task = asyncio.create_task(status.run(handler))
            await entered.wait()
            try:
                self.assertFalse(control.enabled)
                self.assertFalse(await status.run(handler))
                status.cancel()
                self.assertFalse(control.enabled)
            finally:
                release.set()
                await task
            self.assertEqual(1, len(calls))
            self.assertTrue(control.enabled)
            self.assertFalse(disabled.enabled)
            self.assertEqual("cancelled", status.jobs.status)
