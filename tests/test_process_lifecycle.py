"""Owned subprocess regressions using synthetic processes and temporary state."""

import asyncio
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from service.tools import owned_process
from service.tools.tool_workers import ToolWorkers


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_spawn_reaps_process_created_by_thread(self):
        entered, release = threading.Event(), threading.Event()
        created = []
        real_spawn = subprocess.Popen

        def delayed(*args, **kwargs):
            entered.set()
            release.wait(3)
            process = real_spawn(*args, **kwargs)
            created.append(process)
            return process

        with patch.object(owned_process.subprocess, 'Popen', delayed):
            task = asyncio.create_task(owned_process.spawn([sys.executable, '-c', 'import time; time.sleep(60)']))
            await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(len(created), 1)
        self.assertIsNotNone(created[0].poll())

    @unittest.skipUnless(os.name == 'posix', 'POSIX process group regression')
    async def test_group_cleanup_kills_child_after_leader_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            heartbeat = Path(directory) / 'heartbeat'
            child = "import signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); p=pathlib.Path(" + repr(str(heartbeat)) + ");\nwhile True: p.write_text(str(time.time_ns())); time.sleep(.02)"
            parent = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",' + repr(child) + ']); time.sleep(60)'
            process = await owned_process.spawn([sys.executable, '-c', parent], group=True)
            try:
                async with asyncio.timeout(5):
                    while not heartbeat.exists():
                        await asyncio.sleep(.02)
                await asyncio.to_thread(owned_process.stop, process, group=True, timeout=.2)
                first = heartbeat.read_text()
                await asyncio.sleep(.15)
                self.assertEqual(first, heartbeat.read_text())
                self.assertIsNotNone(process.poll())
            finally:
                await asyncio.to_thread(owned_process.stop, process, group=True, timeout=.1)

    async def test_close_waits_for_start_registration(self):
        manager = ToolWorkers()
        key = manager.key('demo', 'counter', 'chat')
        lock = manager.start_locks.setdefault(key, asyncio.Lock())
        await lock.acquire()
        closing = asyncio.create_task(manager.close(*key))
        await asyncio.sleep(0)
        self.assertFalse(closing.done())
        worker = SimpleNamespace(process=Mock(), stop=AsyncMock())
        worker.process.poll.return_value = 0
        manager.items[key] = worker
        lock.release()
        await closing
        worker.stop.assert_awaited_once()
        self.assertNotIn(key, manager.items)

    async def test_monitor_recovers_dead_backend_with_live_frontend(self):
        manager = ToolWorkers()
        key = manager.key('demo', 'counter', 'chat')
        worker = SimpleNamespace(process=Mock(), frontend=Mock(), stop=AsyncMock())
        worker.process.poll.return_value = 1
        worker.frontend.poll.return_value = None
        manager.items[key] = worker
        with patch('service.tools.tool_workers.asyncio.sleep', side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await manager.monitor()
        worker.stop.assert_awaited_once()
        self.assertNotIn(key, manager.items)

    async def test_dead_frontend_does_not_interrupt_current_writer(self):
        manager = ToolWorkers()
        worker = SimpleNamespace(process=Mock(), frontend=Mock(), stop=AsyncMock())
        worker.process.poll.return_value = None
        worker.frontend.poll.return_value = 1
        manager.items[manager.key('demo', 'counter', 'chat')] = worker
        manager.status = AsyncMock(return_value={'running': True})
        with patch('service.tools.tool_workers.asyncio.sleep', side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await manager.monitor()
        worker.stop.assert_not_awaited()

    async def test_exit_acknowledges_only_after_drain_and_cleanup(self):
        from service.tools.exit_handshake import watch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'stop-jobs').touch()
            workers = SimpleNamespace(stopping=False, prepare_exit=AsyncMock(side_effect=[False, True]), shutdown=AsyncMock())
            checks, runs = SimpleNamespace(close=AsyncMock()), SimpleNamespace(close=AsyncMock())
            with patch.dict(os.environ, {'CALABASH_SELECTION_DIR': directory}):
                await watch(workers, checks, runs)
            self.assertTrue(workers.stopping)
            self.assertEqual(workers.prepare_exit.await_count, 2)
            workers.shutdown.assert_awaited_once()
            self.assertTrue((root / 'exit-ready').is_file())

    async def test_prepare_exit_blocks_sdk_admission(self):
        from fastapi import HTTPException, Request
        from service.tools.tool_sdk import ToolSDK
        with tempfile.TemporaryDirectory() as directory, patch('core.local_paths.Path.home', return_value=Path(directory)):
            sdk = ToolSDK('demo', 'counter')
            sdk.host_token = 'synthetic-host'
            sdk.prepare_exit(Request({'type': 'http', 'headers': [(b'x-calabash-host', b'synthetic-host')]}))
            with self.assertRaises(HTTPException):
                sdk.start_batch([1], AsyncMock())

    async def test_build_timeout_reaps_compiler_and_keeps_diagnostics(self):
        from service.tools import tool_workers
        real_thread = asyncio.to_thread
        created = []

        async def compiler(*args, **kwargs):
            process = await owned_process.spawn([sys.executable, '-c', 'import time; time.sleep(60)'], group=True)
            created.append(process)
            return process

        async def timeout_wait(function, *args, **kwargs):
            if kwargs.get('timeout') == 90:
                raise subprocess.TimeoutExpired('synthetic-compiler', 90)
            return await real_thread(function, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(tool_workers, 'app_dir', return_value=Path(directory)), \
                 patch.object(tool_workers.bundles, 'validate'), \
                 patch('service.tools.api_contracts.prepare'), \
                 patch.object(tool_workers, 'frontend_runtime', return_value=('synthetic-node', Path('synthetic-script'))), \
                 patch.object(tool_workers, 'spawn', compiler), \
                 patch.object(tool_workers.asyncio, 'to_thread', timeout_wait):
                with self.assertRaises(tool_workers.FrontendBuildError) as failure:
                    await tool_workers.build_bundle({})
                self.assertTrue((failure.exception.root / 'build.log').is_file())
            self.assertIsNotNone(created[0].poll())

    async def test_safe_exit_finishes_current_item_and_rejects_new_batch(self):
        from fastapi import HTTPException, Request
        from service.tools.tool_sdk import ToolSDK
        with tempfile.TemporaryDirectory() as directory, patch('core.local_paths.Path.home', return_value=Path(directory)):
            sdk = ToolSDK('demo', 'counter')
            sdk.host_token = 'synthetic-host'
            started, finish = asyncio.Event(), asyncio.Event()
            completed = []

            async def writer(value):
                started.set()
                await finish.wait()
                completed.append(value)

            sdk.start_batch([1, 2], writer)
            await started.wait()
            response = sdk.prepare_exit(Request({'type': 'http', 'headers': [(b'x-calabash-host', b'synthetic-host')]}))
            self.assertTrue(response['running'])
            with self.assertRaises(HTTPException):
                sdk.start_batch([3], writer)
            finish.set()
            await sdk.shutdown()
            self.assertEqual(completed, [1])
            self.assertFalse(sdk.status()['running'])
