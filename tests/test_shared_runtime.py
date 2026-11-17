"""Real shared HTTP origins, module versions and safe bounded business work."""
import asyncio
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from service.tools import tool_bundles as bundles
from service.tools.tool_workers import ToolWorkers
from tests.test_tool_bundles import fixture


class RuntimeFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'HOME': self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        from core.logger import get_logger
        get_logger(__name__)  # Match executor startup: configure logging before per-run sinks.
        self.manager = ToolWorkers()
        self.addAsyncCleanup(self.cleanup_runtime)
        self.dist = Path(self.temp.name) / 'dist'
        self.dist.mkdir()
        (self.dist / 'index.html').write_text('<html><head></head><body>synthetic</body></html>')

    async def cleanup_runtime(self):
        while not await self.manager.prepare_exit():
            await asyncio.sleep(.01)
        await self.manager.shutdown()

    def publish(self, name, label, expected=''):
        files = fixture(name)
        files['backend/helpers.py'] = 'LABEL = ' + repr(label)
        files['backend/main.py'] = '''import os
from .helpers import LABEL

def setup(app, sdk):
    @app.get('/api/state', operation_id='read_state')
    def state():
        return {'label': LABEL, 'pid': os.getpid(), 'saved': sdk.get_setting('saved', 0)}
    def scheduled():
        sdk.set_setting('runs', sdk.get_setting('runs', 0) + 1)
    sdk.register_task('refresh', 'Synthetic refresh', scheduled)
'''
        return bundles.write('demo', name, files, expected, built_dist=self.dist)

    async def get(self, worker, token=None, origin=None):
        headers = {'Authorization': 'Bearer ' + (token or worker.token)}
        if origin:
            headers['Origin'] = origin
        async with httpx.AsyncClient(trust_env=False) as client:
            return await client.get(f'http://127.0.0.1:{worker.port}/api/state', headers=headers)



class SharedRuntimeTests(RuntimeFixture):
    async def test_tools_share_pid_without_spawning_and_keep_distinct_origins_and_modules(self):
        first = self.publish('one', 'first')
        self.publish('two', 'second')
        with patch('subprocess.Popen', side_effect=AssertionError('Tools must not spawn a process')):
            one = await self.manager.open('demo', 'one')
            two = await self.manager.open('demo', 'two')
        self.assertNotEqual(one.port, two.port)
        self.assertIs(one, await self.manager.open('demo', 'one'))
        self.assertEqual(os.getpid(), (await self.get(one)).json()['pid'])
        self.assertEqual('second', (await self.get(two)).json()['label'])
        self.assertEqual(403, (await self.get(two, one.token)).status_code)
        self.assertEqual(403, (await self.get(two, origin=f'http://127.0.0.1:{one.port}')).status_code)
        one.sdk.set_setting('saved', 7)
        self.publish('one', 'changed', first['revision'])
        self.assertEqual('first', (await self.get(one)).json()['label'])
        await self.manager.close('demo', 'one')
        one = await self.manager.open('demo', 'one')
        self.assertEqual({'label': 'changed', 'pid': os.getpid(), 'saved': 7}, (await self.get(one)).json())
        self.assertEqual('second', (await self.get(two)).json()['label'])

    async def test_file_thread_keeps_controls_responsive_and_close_waits_for_safe_stop(self):
        self.publish('one', 'first')
        self.publish('two', 'second')
        one = await self.manager.open('demo', 'one')
        two = await self.manager.open('demo', 'two')
        entered, finish = threading.Event(), threading.Event()
        written = []
        def writer(value):
            entered.set()
            if not finish.wait(5):
                raise TimeoutError('synthetic release missing')
            written.append(value)
        async def handle(value):
            await one.sdk.io(writer, value)
        one.sdk.start_batch([1, 2], handle)
        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
        try:
            response = await asyncio.wait_for(self.get(two), 1)
            self.assertEqual(200, response.status_code)
            with self.assertRaises(ValueError):
                await self.manager.close('demo', 'one')
            self.assertEqual([], written)
        finally:
            finish.set()
            await one.sdk.task
        self.assertEqual([1], written)
        await self.manager.close('demo', 'one')
        self.assertTrue(two.alive)
        self.assertEqual(200, (await self.get(two)).status_code)
