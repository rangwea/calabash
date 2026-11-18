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
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}), patch('backend.harness_bridge.workers.prepare_exit', new=AsyncMock(return_value=True)), patch('backend.harness_bridge.workers.shutdown', new=AsyncMock()) as shutdown:
            await serve(request, output)
            shutdown.assert_awaited_once()
        response = json.loads(output.getvalue())
        self.assertEqual('1', response['id'])
        self.assertEqual('operation_failed', response['error']['code'])
        self.assertNotIn('Traceback', output.getvalue())

    async def test_oversize_frame_stops_instead_of_parsing_tail(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}), patch('backend.harness_bridge.workers.prepare_exit', new=AsyncMock(return_value=True)), patch('backend.harness_bridge.workers.shutdown', new=AsyncMock()):
            await serve(io.BytesIO(b'x' * (2 * 1024 * 1024 + 1) + b'\n'), output)
        self.assertEqual('', output.getvalue())

    async def test_eof_waits_for_current_item_before_reaping(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}), patch('backend.harness_bridge.workers.prepare_exit', new=AsyncMock(side_effect=[False, True])) as prepare, patch('backend.harness_bridge.workers.shutdown', new=AsyncMock()) as shutdown, patch('backend.harness_bridge.asyncio.sleep', new=AsyncMock()):
            await serve(io.BytesIO(b''), io.StringIO())
            self.assertEqual(2, prepare.await_count)
            shutdown.assert_awaited_once()


class ConcurrentBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_request_does_not_block_query_and_eof_drains(self):
        import asyncio
        release = asyncio.Event()
        async def fake(method, params):
            if method == 'slow':
                await release.wait()
                return 'finished'
            release.set()
            return 'query'
        requests = io.BytesIO(b'{"id":"slow","method":"slow","params":{}}\n{"id":"fast","method":"fast","params":{}}\n')
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}), patch('backend.harness_bridge.dispatch', side_effect=fake), patch('backend.harness_bridge.workers.prepare_exit', new=AsyncMock(return_value=True)), patch('backend.harness_bridge.workers.shutdown', new=AsyncMock()):
            await asyncio.wait_for(serve(requests, output), 2)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(['fast', 'slow'], [value['id'] for value in responses])

    async def test_same_tool_serializes_while_other_tool_can_run(self):
        import asyncio
        active, overlap, concurrent = {}, [], []
        async def fake(method, params):
            name = params['name']
            active[name] = active.get(name, 0) + 1
            overlap.append(active[name])
            concurrent.append(sum(active.values()))
            await asyncio.sleep(.02)
            active[name] -= 1
            return True
        data = b''.join(json.dumps({'id': str(i), 'method': 'tools.open', 'params': {'project': 'demo', 'name': name}}).encode() + b'\n' for i, name in enumerate(['first', 'first', 'other']))
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}), patch('backend.harness_bridge.dispatch', side_effect=fake), patch('backend.harness_bridge.workers.prepare_exit', new=AsyncMock(return_value=True)), patch('backend.harness_bridge.workers.shutdown', new=AsyncMock()):
            await serve(io.BytesIO(data), io.StringIO())
        self.assertEqual(1, max(overlap))
        self.assertGreater(max(concurrent), 1)

    async def test_same_session_operations_serialize_even_with_different_tool_names(self):
        import asyncio
        active, overlap, parallel = {}, [], []

        async def fake(method, params):
            session = params['session']
            active[session] = active.get(session, 0) + 1
            overlap.append(active[session])
            parallel.append(sum(active.values()))
            await asyncio.sleep(.02)
            active[session] -= 1
            return True

        data = b''.join(json.dumps({'id': str(index), 'method': 'agent.call', 'params': {
            'session': session, 'arguments': {'project': 'demo', 'name': name}}}).encode() + b'\n'
            for index, (session, name) in enumerate([('a', 'first'), ('a', 'second'), ('b', 'other')]))
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}), patch('backend.harness_bridge.dispatch', side_effect=fake), patch('backend.harness_bridge.workers.prepare_exit', new=AsyncMock(return_value=True)), patch('backend.harness_bridge.workers.shutdown', new=AsyncMock()):
            await serve(io.BytesIO(data), io.StringIO())
        self.assertEqual(1, max(overlap))
        self.assertGreater(max(parallel), 1)
