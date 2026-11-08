"""Harness transport checks use synthetic tools and no model calls."""
import io
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from backend.harness_bridge import dispatch, serve


class HarnessBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_unbounded_operations_and_paths(self):
        for method, params in [('shell', {}), ('tools.open', {'project': '../x', 'name': 'x'}),
                               ('tools.list', {'path': '/'}), ('tools.open', {'project': 'a', 'name': 'b', 'token': 'x'})]:
            with self.assertRaises(ValueError):
                await dispatch(method, params)

    async def test_open_does_not_disclose_host_token(self):
        from types import SimpleNamespace
        with patch('backend.harness_bridge.workers.open', new=AsyncMock(return_value=SimpleNamespace(url='http://127.0.0.1:1234/', host_token='secret'))):
            result = await dispatch('tools.open', {'project': 'demo', 'name': 'test'})
        self.assertNotIn('secret', json.dumps(result))

    async def test_eof_reaps_workers_and_error_is_sanitized(self):
        output = io.StringIO()
        request = io.BytesIO(b'{"id":"1","method":"shell","params":{}}\n')
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}), patch('backend.harness_bridge.workers.prepare_exit', new=AsyncMock(return_value=True)), patch('backend.harness_bridge.workers.shutdown', new=AsyncMock()) as shutdown:
            await serve(request, output)
            shutdown.assert_awaited_once()
        response = json.loads(output.getvalue())
        self.assertEqual('1', response['id'])
        self.assertEqual('operation_failed', response['error']['code'])
        self.assertNotIn('Traceback', output.getvalue())

    async def test_oversize_frame_stops_instead_of_parsing_tail(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}), patch('backend.harness_bridge.workers.prepare_exit', new=AsyncMock(return_value=True)), patch('backend.harness_bridge.workers.shutdown', new=AsyncMock()):
            await serve(io.BytesIO(b'x' * (2 * 1024 * 1024 + 1) + b'\n'), output)
        self.assertEqual('', output.getvalue())

    async def test_eof_waits_for_current_item_before_reaping(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}), patch('backend.harness_bridge.workers.prepare_exit', new=AsyncMock(side_effect=[False, True])) as prepare, patch('backend.harness_bridge.workers.shutdown', new=AsyncMock()) as shutdown, patch('backend.harness_bridge.asyncio.sleep', new=AsyncMock()):
            await serve(io.BytesIO(b''), io.StringIO())
            self.assertEqual(2, prepare.await_count)
            shutdown.assert_awaited_once()
