"""The shipped starter must compile and expose precise type diagnostics."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.tools.api_contracts import extract
from service.tools.tool_bundles import validate
from service.tools.tool_templates import base_template
from service.tools.tool_workers import FrontendBuildError, build_bundle


class TemplateTests(unittest.TestCase):
    def test_identity_and_typed_backend(self):
        files = base_template('demo', 'starter')
        validate(files, 'demo', 'starter')
        self.assertEqual('create_message', extract(files)['operations'][0]['name'])
        with self.assertRaises(ValueError):
            base_template('../escape', 'starter')
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}):
            os.environ['HOME'] = temporary
            path = Path(temporary) / 'main.py'
            path.write_text(files['backend/main.py'])
            spec = importlib.util.spec_from_file_location('synthetic_starter', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            app = FastAPI()
            module.setup(app, None)
            with TestClient(app) as client:
                self.assertEqual({'message': 'Hello'}, client.post('/api/message', json={'text': ' Hello '}).json())
                self.assertEqual(422, client.post('/api/message', json={'text': 123}).status_code)
                self.assertEqual(422, client.post('/api/message', json={'text': 'ok', 'unknown': True}).status_code)


    def test_type_evidence_does_not_return_source_literals(self):
        from service.tools.type_diagnostics import type_evidence
        self.assertEqual({}, type_evidence("Type 'private-business-value' is not assignable to type 'string'."))
        self.assertEqual({'property': 'missingProp'}, type_evidence("Property 'missingProp' does not exist on type 'Thing'."))


class TemplateBuildTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {'HOME': temporary.name})
        environment.start()
        self.addCleanup(environment.stop)

    async def test_build_and_actionable_prop_and_contract_diagnostics(self):
        files = base_template('demo', 'starter')
        built = await build_bundle(files)
        self.assertTrue((built / 'dist/index.html').is_file())
        broken = dict(files)
        broken['frontend/App.tsx'] = files['frontend/App.tsx'].replace('text: text.trim()', 'text: 123').replace('type="primary"', 'type="invalid-variant"')
        with self.assertRaises(FrontendBuildError) as caught:
            await build_bundle(broken)
        diagnostics = caught.exception.diagnostics
        self.assertTrue(any(item.get('actual_type') == 'number' and item.get('expected_type') == 'string' for item in diagnostics), diagnostics)
        self.assertTrue(any(item['line'] > 0 for item in diagnostics), diagnostics)
        from service.tools import check_records

        revision = 'a' * 64
        check_records.record('demo', 'starter', 'starterchat', {'revision': revision, 'state': 'failed', 'diagnostics': diagnostics})
        restored = check_records.read('demo', 'starter', 'starterchat', revision)['diagnostics']
        self.assertTrue(any(item.get('expected_type') == 'string' for item in restored))
        for item in diagnostics:
            self.assertEqual('frontend/App.tsx', item['file'])
            self.assertGreater(item['line'], 0)
            self.assertTrue(item['code'].startswith('TS'))
