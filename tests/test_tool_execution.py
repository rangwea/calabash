"""A shared bounded file pool must not cancel a still-running file writer."""
import asyncio
import threading
import unittest

from service.tools.tool_execution import Execution, execution, io


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_waits_for_thread_and_limits_parallel_file_work(self):
        gate, started = threading.Event(), threading.Event()
        lock = threading.Lock()
        counts = {'active': 0, 'peak': 0, 'finished': 0}
        def writer():
            with lock:
                counts['active'] += 1
                counts['peak'] = max(counts['peak'], counts['active'])
                started.set()
            if not gate.wait(3):
                raise TimeoutError('synthetic writer release missing')
            with lock:
                counts['active'] -= 1
                counts['finished'] += 1
        tasks = [asyncio.create_task(io(writer)) for _ in range(8)]
        await asyncio.to_thread(started.wait, 1)
        tasks[0].cancel()
        await asyncio.sleep(.02)
        self.assertFalse(tasks[0].done())
        gate.set()
        result = await asyncio.gather(*tasks, return_exceptions=True)
        self.assertIsInstance(result[0], asyncio.CancelledError)
        self.assertLessEqual(counts['peak'], 4)
        self.assertEqual(8, counts['finished'])

    async def test_reservation_budget_is_returned_and_never_drifts(self):
        scheduler = Execution()
        for _ in range(32):
            scheduler.reserve()
        with self.assertRaises(Exception) as full:
            scheduler.reserve()
        self.assertIn('queue is full', str(full.exception))
        for _ in range(32):
            scheduler.release()
        self.assertEqual(0, scheduler.pending)
        # A release without a matching reserve is a bug, not extra capacity.
        with self.assertRaises(RuntimeError):
            scheduler.release()
        self.assertEqual(0, scheduler.pending)
        scheduler.reserve()
        self.assertEqual(1, scheduler.pending)
        scheduler.release()

    async def test_failed_batch_start_does_not_consume_a_slot(self):
        """A rejected batch must return its reservation, not shrink the shared budget."""
        from unittest.mock import patch

        from service.tools.tool_sdk import ToolSDK
        sdk = ToolSDK('demo', 'counter')
        sdk.loop = asyncio.get_running_loop()
        scheduler = execution(sdk.loop)
        before = scheduler.pending
        with patch('service.tools.tool_sdk.ToolJobs', side_effect=ValueError('synthetic failure')):
            with self.assertRaises(ValueError):
                sdk.start_batch([], lambda *_: None)
        self.assertEqual(before, scheduler.pending)
        self.assertIsNone(sdk.jobs)
