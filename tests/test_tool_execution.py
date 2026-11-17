"""A shared bounded file pool must not cancel a still-running file writer."""
import asyncio
import threading
import unittest

from service.tools.tool_execution import io


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
