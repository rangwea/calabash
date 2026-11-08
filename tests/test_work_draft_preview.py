"""Real preview reads working Vue files directly; backend source is not HTTP-visible."""
import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from service.tools import tool_bundles as bundles
from service.tools import work_drafts
from service.tools.tool_workers import workers
from tests.test_vue_workspace import fixture


@unittest.skipUnless(shutil.which('node') and Path('node_modules/vue').is_dir(), 'Local preview compiler required')
class WorkDraftPreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_hmr_uses_same_source_directory_without_copying_or_reopening(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'HOME': temporary}):
            bundles.write('demo', 'counter', fixture(), chat_id='chat')
            worker = await workers.open('demo', 'counter', 'chat')
            pid = worker.frontend.pid
            root = bundles.directory('demo', 'counter', 'chat').resolve()
            try:
                self.assertFalse((worker.root / 'frontend/App.vue').exists())
                self.assertEqual(0, (worker.root / 'backend/main.py').stat().st_mode & 0o222)
                async with httpx.AsyncClient(trust_env=False, follow_redirects=True) as client:
                    await client.get(worker.url)
                    path = root / 'frontend/App.vue'
                    url = f'http://127.0.0.1:{worker.frontend_port}/@fs/{path}'
                    first = await client.get(url)
                    self.assertEqual(200, first.status_code)
                    self.assertIn('Increment', first.text)
                    original = path.read_text()
                    work_drafts.observe('chat', 'demo', 'counter', 'frontend/App.vue', original)
                    work_drafts.write_files('chat', 'preview-edit', 'demo', 'counter', {'frontend/App.vue': original.replace('Increment', 'Increase')})
                    for _ in range(40):
                        updated = await client.get(url)
                        if 'Increase' in updated.text:
                            break
                        await asyncio.sleep(.05)
                    self.assertEqual(200, updated.status_code)
                    self.assertTrue('Increase' in updated.text, 'Vite did not observe the atomic working-file update')
                    self.assertEqual(pid, worker.frontend.pid)
                    hidden = await client.get(f'http://127.0.0.1:{worker.frontend_port}/@fs/{root}/backend/main.py')
                    self.assertEqual(403, hidden.status_code)
                    self.assertEqual(0, (await client.get(f'http://127.0.0.1:{worker.frontend_port}/api/state')).json()['count'])
                    backend = (root / 'backend/main.py').read_text()
                    work_drafts.observe('chat', 'demo', 'counter', 'backend/main.py', backend)
                    work_drafts.write_files('chat', 'preview-edit', 'demo', 'counter', {'backend/main.py': backend.replace('"count": 0', '"count": 7')})
                    self.assertEqual(0, (await client.get(f'http://127.0.0.1:{worker.frontend_port}/api/state')).json()['count'])
                    self.assertFalse(list(root.rglob('__pycache__')))
                    await workers.close('demo', 'counter', 'chat')
                    worker = await workers.open('demo', 'counter', 'chat')
                    await client.get(worker.url)
                    self.assertEqual(7, (await client.get(f'http://127.0.0.1:{worker.frontend_port}/api/state')).json()['count'])
            finally:
                work_drafts.release('preview-edit')
                await workers.close('demo', 'counter', 'chat')
