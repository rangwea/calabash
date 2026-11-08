"""Connection probes are read-only and preserve running-task uncertainty."""
import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

from service.tools.tool_health import snapshot
from service.tools.tool_workers import workers


class ToolHealthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = patch('service.tools.tool_workers.app_dir', return_value=self.temp.name)
        self.path.start()
        self.addCleanup(self.path.stop)
        self.key = workers.key('demo', 'synthetic')
        self.addCleanup(lambda: workers.items.pop(self.key, None))
        self.addCleanup(lambda: workers.failures.pop(self.key, None))
        self.addCleanup(lambda: workers.start_locks.pop(self.key, None))
        self.worker = SimpleNamespace(process=Mock(), frontend=Mock(), frontend_port=1235, port=1234, token='synthetic-only')
        self.worker.process.poll.return_value = None
        self.worker.frontend.poll.return_value = None

    async def test_absent_failed_and_starting_are_distinct_without_opening(self):
        with patch.object(workers, 'open', AsyncMock()) as opened:
            self.assertEqual('closed', (await snapshot('demo', 'synthetic'))['state'])
            workers.failures[self.key] = self.worker
            self.assertEqual('unavailable', (await snapshot('demo', 'synthetic'))['state'])
            lock = asyncio.Lock()
            workers.start_locks[self.key] = lock
            async with lock:
                self.assertEqual('starting', (await snapshot('demo', 'synthetic'))['state'])
            opened.assert_not_called()

    async def test_dead_worker_does_not_issue_network_requests(self):
        workers.items[self.key] = self.worker
        self.worker.process.poll.return_value = 1
        with patch('service.tools.tool_health.httpx.AsyncClient') as client:
            self.assertEqual(False, (await snapshot('demo', 'synthetic'))['running'])
            client.assert_not_called()

    async def test_frontend_loss_keeps_background_running_and_connection_loss_is_unknown(self):
        workers.items[self.key] = self.worker
        original = httpx.AsyncClient
        response = {'running': True}
        def handle(request):
            self.assertEqual('GET', request.method)
            self.assertEqual('/api/sdk/status', request.url.path)
            return httpx.Response(200, json=response)
        with patch('service.tools.tool_health.httpx.AsyncClient', side_effect=lambda **options: original(transport=httpx.MockTransport(handle))):
            self.assertEqual('ready', (await snapshot('demo', 'synthetic'))['state'])
            self.worker.frontend.poll.return_value = 1
            result = await snapshot('demo', 'synthetic')
            self.assertEqual('unavailable', result['state'])
            self.assertTrue(result['running'])
            self.assertNotIn('synthetic-only', str(result))
        def disconnected(request):
            raise httpx.ConnectError('gone', request=request)
        with patch('service.tools.tool_health.httpx.AsyncClient', side_effect=lambda **options: original(transport=httpx.MockTransport(disconnected))):
            self.assertIsNone((await snapshot('demo', 'synthetic'))['running'])


class RuntimeEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_endpoint_requires_session_and_never_opens_tool(self):
        from api import bundle_api
        from core.workspace_app import create_workspace_app
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'HOME': temporary}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_workspace_app()), base_url='http://127.0.0.1') as client:
                self.assertEqual(403, (await client.get('/api/workspace/tools/demo/synthetic/runtime')).status_code)
                await client.get('/')
                client.headers['X-Calabash-Request'] = 'workspace'
                with patch.object(workers, 'open', AsyncMock()) as opened:
                    result = await client.get('/api/workspace/tools/demo/synthetic/runtime')
                    self.assertEqual('closed', result.json()['state'])
                    self.assertEqual(404, (await client.get('/api/workspace/tools/demo/synthetic/runtime?chat_id=missing')).status_code)
                    opened.assert_not_called()
                dead = SimpleNamespace(process=Mock())
                dead.process.poll.return_value = 1
                key = workers.key('demo', 'synthetic')
                with patch.dict(workers.items, {key: dead}), patch.object(workers, 'status', AsyncMock()) as status:
                    self.assertEqual({'running': False}, await bundle_api.status('demo', 'synthetic'))
                    status.assert_not_called()
