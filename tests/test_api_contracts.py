"""Static contract generation, real compilation and synthetic CRM operations."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.tool_worker import create_tool_app
from service.tools.api_contracts import ContractError, client_source, extract
from service.tools.tool_workers import FrontendBuildError, build_bundle
from tests.fixtures.crm_contract import fixture


class ContractTests(unittest.TestCase):
    def test_contract_comes_from_python_and_never_imports_tool_code(self):
        files = fixture()
        files['backend/main.py'] = 'raise RuntimeError("must never execute during generation")\n' + files['backend/main.py'].replace('from __future__ import annotations\n', '')
        contract = extract(files)
        self.assertEqual(6, len(contract['operations']))
        self.assertEqual('number', contract['operations'][2]['params']['customer_id']['type'])
        client = client_source(contract)
        self.assertIn('export interface Customer extends CustomerInput', client)
        self.assertIn('"stage"?: string', client)
        self.assertIn('create_customer:', client)
        self.assertIn('body: CustomerInput', client)
        self.assertNotIn('any', client)

    def test_unsupported_types_and_field_aliases_are_explicit_diagnostics(self):
        for source in (fixture()['backend/main.py'].replace('name: str = Field(', 'name: bytes = Field('),
                       fixture()['backend/main.py'].replace('min_length=1, max_length=100', 'alias="displayName"')):
            with self.subTest(source=source[:20]), self.assertRaises(ContractError) as caught:
                extract({'backend/main.py': source})
            self.assertEqual('backend/main.py', caught.exception.diagnostic['file'])
            self.assertGreater(caught.exception.diagnostic['line'], 0)


class CRMContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'HOME': self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        self.root = Path(self.temp.name) / 'tool'
        for file, content in fixture().items():
            path = self.root / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.config = {'root': str(self.root), 'project': 'demo', 'name': 'crm_contract',
                       'port': 1234, 'origin': 'http://127.0.0.1:1234', 'token': 'synthetic'}

    def client(self):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_tool_app(self.config)),
                                 base_url=self.config['origin'], headers={'Authorization': 'Bearer synthetic'})

    async def test_create_edit_filter_followup_and_reopen_preserve_data(self):
        async with self.client() as client:
            created = await client.post('/api/customers', json={'name': 'Synthetic A'})
            self.assertEqual(200, created.status_code, created.text)
            customer_id = created.json()['id']
            await client.post('/api/customers', json={'name': 'Synthetic B'})
            changed = await client.put(f'/api/customers/{customer_id}', json={'name': 'Edited A', 'stage': 'Contacted'})
            self.assertEqual('Contacted', changed.json()['stage'])
            selected = await client.get('/api/customers', params={'q': 'Edited'})
            self.assertEqual([customer_id], [row['id'] for row in selected.json()])
            note = await client.post(f'/api/customers/{customer_id}/followups', json={'note': 'Synthetic follow-up'})
            self.assertEqual(200, note.status_code)
        # New app and SDK instance simulate closing and reopening the tool.
        async with self.client() as client:
            detail = (await client.get(f'/api/customers/{customer_id}')).json()
            self.assertEqual('Edited A', detail['name'])
            self.assertEqual('Synthetic follow-up', detail['followups'][0]['note'])
            self.assertEqual(2, len((await client.get('/api/customers')).json()))
            self.assertEqual(200, (await client.delete(f'/api/customers/{customer_id}')).status_code)
            self.assertEqual(404, (await client.get(f'/api/customers/{customer_id}')).status_code)


    async def test_errors_keep_operation_and_frames_without_input_or_exception_values(self):
        source = self.root / 'backend/main.py'
        source.write_text(source.read_text() + '''
    @app.get('/api/broken', operation_id='broken_response', response_model=Customer)
    def broken_response():
        return {'name': 'synthetic-secret-value'}

    @app.get('/api/crash')
    def crash():
        raise ValueError('synthetic-secret-value')
''')
        with self.assertLogs('service.tools.api_errors', level='ERROR') as logs:
            async with self.client() as client:
                for method, path, options, status in [
                    ('POST', '/api/customers', {'json': {'name': {'private': 'synthetic-secret-value'}, 'privateBusinessField': 'synthetic-secret-value'}}, 422),
                    ('GET', '/api/broken', {}, 500), ('GET', '/api/crash', {}, 500),
                ]:
                    response = await client.request(method, path, **options)
                    self.assertEqual(status, response.status_code)
                    self.assertEqual(response.headers['X-Calabash-Request-Id'], response.json()['error']['request_id'])
                    self.assertNotIn('synthetic-secret-value', response.text)
        records = '\n'.join(logs.output)
        self.assertIn('response_validation_failed', records)
        self.assertIn('create_customer', records)
        self.assertIn('backend/main.py', records)
        self.assertIn('ValueError', records)
        self.assertNotIn('synthetic-secret-value', records)
        self.assertNotIn('privateBusinessField', records)

    async def test_real_typescript_build_rejects_wrong_body_then_accepts_typed_crm(self):
        files = fixture()
        invalid = {**files, 'frontend/App.tsx': files['frontend/App.tsx'].replace('body:{name}', 'body:{name:123}')}
        with self.assertRaises(FrontendBuildError) as caught:
            await build_bundle(invalid)
        self.assertTrue(any(item.get('code') == 'TS2322' for item in caught.exception.diagnostics))
        built = await build_bundle(files)
        self.assertTrue((built / 'dist/index.html').is_file())
        self.assertNotIn('calabash-api.ts', files)
        self.assertIn('create_customer', (built / 'calabash-api.ts').read_text())
