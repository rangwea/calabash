"""Synthetic page/API evidence: no business probing, values or real model calls."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.tool_worker import create_tool_app
from service.tools import harness_workspace as workspace
from service.tools.preview_diagnostics import PreviewDiagnostics, clean

SOURCE = '''from pydantic import BaseModel
class Answer(BaseModel):
    text: str

def setup(app, sdk):
    @app.get('/api/read', response_model=Answer, operation_id='read_answer')
    def read_answer() -> Answer:
        raise RuntimeError('PRIVATE-FAILURE-CONTENT')

    @app.post('/api/write', response_model=Answer, operation_id='write_answer')
    def write_answer() -> Answer:
        raise RuntimeError('BUSINESS-WRITE-MUST-NOT-EXECUTE')
'''


class PreviewDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'HOME': self.temp.name})
        self.environment.start()
        self.root = Path(self.temp.name) / ('a' * 32)
        (self.root / 'backend').mkdir(parents=True)
        (self.root / 'backend/main.py').write_text(SOURCE)
        self.app = create_tool_app({'root': str(self.root), 'project': 'demo', 'name': 'diagnostic',
                                    'origin': 'http://127.0.0.1:1234', 'port': 1234, 'token': 'synthetic',
                                    'host_token': 'host-only', 'revision': 'b' * 64, 'diagnostic_owner': 'synthetic-session'})
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://127.0.0.1:1234', headers={'Authorization': 'Bearer synthetic'})

    async def asyncTearDown(self):
        await self.client.aclose()
        self.environment.stop()
        self.temp.cleanup()

    async def report(self):
        response = await self.client.get('/api/sdk/verification', headers={'X-Calabash-Host': 'host-only'})
        self.assertEqual(200, response.status_code)
        return response.json()

    async def test_registration_checks_do_not_invoke_even_get_handlers(self):
        report = await self.report()
        self.assertEqual('passed', report['interfaces'])
        self.assertEqual(2, report['verified_operations'])
        self.assertFalse(report['business_verified'])
        self.assertEqual([], report['diagnostics'])
        self.assertEqual('pending', report['page'])
        self.assertEqual(403, (await self.client.get('/api/sdk/verification')).status_code)
        self.assertEqual(403, (await self.client.post('/api/sdk/verification', json={'code': 'MODULE_HTTP'})).status_code)

    async def test_page_errors_are_bounded_and_never_retain_content(self):
        await self.client.post('/api/sdk/page-evidence', json={'code': 'PAGE_READY'})
        self.assertEqual('ready', (await self.report())['page'])
        await self.client.post('/api/sdk/page-evidence', json={'code': 'PAGE_SCRIPT', 'file': 'frontend/App.tsx', 'line': 42, 'message': 'PRIVATE-TEXT', 'stack': 'SECRET-STACK', 'input': 'SECRET-INPUT'})
        for _ in range(40):
            await self.client.post('/api/sdk/page-evidence', json={'code': 'PAGE_SCRIPT', 'file': 'frontend/App.tsx', 'line': 42})
        await self.client.post('/api/sdk/page-evidence', json={'code': 'PAGE_READY'})
        report = await self.report()
        self.assertEqual('failed', report['page'])
        self.assertEqual(2, len(report['diagnostics']))
        self.assertEqual('frontend/App.tsx', report['diagnostics'][1]['file'])
        self.assertIn('not_source_line', report['diagnostics'][1]['location_kind'])
        records = list(Path(self.temp.name).glob('.calabash/diagnostics/**/runs/*.json'))
        self.assertEqual(1, len(records))
        content = records[0].read_text()
        self.assertNotIn('SECRET', content)
        self.assertNotIn('PRIVATE', content)
        self.assertEqual(400, (await self.client.post('/api/sdk/page-evidence', json={'code': 'API_ROUTE'})).status_code)

    async def test_real_api_failure_keeps_type_and_source_without_error_values(self):
        response = await self.client.get('/api/read')
        self.assertEqual(500, response.status_code)
        report = await self.report()
        failure = report['diagnostics'][0]
        self.assertEqual('API_FAILURE', failure['code'])
        self.assertEqual('RuntimeError', failure['exception'])
        self.assertEqual('read_answer', failure['operation'])
        self.assertEqual('backend/main.py', failure['file'])
        self.assertGreater(failure['line'], 0)
        self.assertNotIn('PRIVATE-FAILURE', json.dumps(report))

    async def test_missing_registration_and_untyped_routes_are_not_success(self):
        from fastapi import FastAPI
        app = FastAPI()
        diagnostics = PreviewDiagnostics('demo', 'diagnostic', 'other', 'c' * 32, 'd' * 64)
        diagnostics.check_interfaces(app, {'backend/main.py': SOURCE})
        self.assertEqual('failed', diagnostics.report()['interfaces'])
        self.assertTrue(all(item['code'] == 'API_ROUTE' for item in diagnostics.report()['diagnostics']))
        app.add_api_route('/api/untyped', lambda: 'not called')
        diagnostics = PreviewDiagnostics('demo', 'diagnostic', 'other', 'c' * 32, 'd' * 64)
        diagnostics.check_interfaces(app, {'backend/main.py': 'def setup(app, sdk):\n    pass\n'})
        self.assertEqual('not_checked', diagnostics.report()['interfaces'])
        self.assertEqual(1, diagnostics.report()['untyped_operations'])
        self.assertNotIn('file', clean({'code': 'PAGE_SCRIPT', 'file': 'frontend/../../secret'}))

    async def test_source_and_session_binding_reject_stale_runtime_before_query(self):
        target = {'project': 'demo', 'name': 'diagnostic'}
        worker = type('Worker', (), {'revision': 'old', 'process': type('Process', (), {'poll': lambda _: None})()})()
        with patch.object(workspace, 'state', return_value=target), patch.object(workspace, 'read_source', return_value={'revision': 'new'}), patch.object(workspace.workers, 'items', {workspace.workers.key('demo', 'diagnostic', workspace.owner('session')): worker}):
            result = await workspace.preview_diagnostics('session')
            self.assertEqual('stale', result['state'])
            self.assertEqual([], result['diagnostics'])
