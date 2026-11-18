"""Electron embedding changes cookie scope, never the worker's origin or token checks."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.tool_worker import create_tool_app


class HarnessEmbedSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_partitioned_cookie_and_foreign_origin_rejection(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}):
            root = Path(home)
            (root / 'backend').mkdir()
            (root / 'dist').mkdir()
            (root / 'backend/main.py').write_text('def setup(app, sdk):\n    pass\n')
            (root / 'dist/index.html').write_text('<html><head></head><body>Test</body></html>')
            config = {'root': home, 'project': 'demo', 'name': 'embed', 'origin': 'http://127.0.0.1:1234', 'port': 1234, 'token': 'synthetic', 'partitioned_session': True}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_tool_app(config)), base_url=config['origin']) as client:
                response = await client.get('/api/sdk/session?session=synthetic', headers={'Sec-Fetch-Site': 'cross-site'})
                self.assertEqual(307, response.status_code)
                cookie = response.headers['set-cookie']
                for attribute in ['HttpOnly', 'Secure', 'SameSite=None', 'Partitioned']:
                    self.assertIn(attribute, cookie)
                self.assertEqual(403, (await client.get('/', headers={'Origin': 'https://other.example', 'Authorization': 'Bearer synthetic'})).status_code)
                self.assertEqual(403, (await client.get('/api/sdk/session?session=wrong', headers={'Sec-Fetch-Site': 'cross-site'})).status_code)
                self.assertEqual(403, (await client.get('/api/sdk/status', headers={'Sec-Fetch-Site': 'cross-site', 'Authorization': 'Bearer synthetic'})).status_code)
