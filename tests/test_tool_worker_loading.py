"""Real request validation and host guard injection, without user data."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.tool_worker import create_tool_app


class WorkerLoadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_postponed_annotations_resolve_and_old_built_pages_get_guard(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'HOME': temp}):
            root = Path(temp)
            (root / 'backend').mkdir()
            (root / 'dist').mkdir()
            (root / 'dist/index.html').write_text('<html><head></head><body>Previously built</body></html>')
            (root / 'backend/main.py').write_text('''from __future__ import annotations
from pydantic import BaseModel
class RecordIn(BaseModel):
    amount: int

def setup(app, sdk):
    @app.post('/api/records')
    def add(record: RecordIn):
        return {'amount': record.amount}
''')
            app = create_tool_app({'root': temp, 'project': 'demo', 'name': 'counter', 'origin': 'http://127.0.0.1:1234', 'port': 1234, 'token': 'synthetic'})
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:1234', headers={'Authorization': 'Bearer synthetic'}) as client:
                response = await client.post('/api/records', json={'amount': 12})
                self.assertEqual(200, response.status_code, response.text)
                self.assertEqual({'amount': 12}, response.json())
                self.assertEqual(422, (await client.post('/api/records', json={'amount': 'invalid'})).status_code)
                page = await client.get('/')
                self.assertIn('/api/sdk/runtime-guard.js', page.text)
                guard = await client.get('/api/sdk/runtime-guard.js')
                self.assertEqual(200, guard.status_code)
                self.assertIn('calabash-tool-issue', guard.text)
                self.assertEqual(200, (await client.post('/api/sdk/runtime-issue', json={'kind': 'request_failed', 'status': 500, 'path': '/api/records?secret=not-logged'})).status_code)
