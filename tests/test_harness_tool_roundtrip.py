"""Real strict build + published React/Python worker through the Harness boundary."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.harness_bridge import dispatch
from service.tools import tool_bundles as bundles
from service.tools.tool_workers import build_bundle, workers
from tests.test_tool_bundles import fixture


@unittest.skipUnless(shutil.which('node') and Path('node_modules/react').is_dir(), 'Frontend compiler required')
class HarnessToolRoundtripTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_open_execute_and_safe_close(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            files = fixture()
            built = await build_bundle(files)
            bundles.write('demo', 'counter', files, built_dist=built / 'dist')
            result = await dispatch('tools.open', {'project': 'demo', 'name': 'counter'})
            try:
                async with httpx.AsyncClient(trust_env=False, follow_redirects=True) as client:
                    response = await client.get(result['url'])
                    self.assertEqual(200, response.status_code)
                    origin = str(response.url).split('/?')[0].rstrip('/')
                    response = await client.get(origin + '/api/state')
                    self.assertEqual(0, response.json()['count'])
            finally:
                await dispatch('tools.close', {'project': 'demo', 'name': 'counter'})
            self.assertFalse(workers.items)

    async def test_agent_draft_manual_preview_and_confirmed_publication(self):
        from service.tools import harness_workspace as workspace
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            session = 'synthetic-office-session'
            try:
                for index, (path, content) in enumerate(fixture().items()):
                    await workspace.agent_call(session, f'write-{index}', 'write_tool_file', {'project': 'demo', 'name': 'counter', 'path': path, 'content': content})
                checked = await workspace.agent_call(session, 'build', 'check_tool_build', {'project': 'demo', 'name': 'counter'})
                self.assertEqual('passed', checked['state'])
                self.assertEqual([], bundles.list_tools())
                workspace.release(session)
                preview = await workspace.preview(session)
                async with httpx.AsyncClient(trust_env=False, follow_redirects=True) as client:
                    response = await client.get(preview['url'])
                    self.assertEqual(200, response.status_code)
                    origin = str(response.url).split('/?')[0].rstrip('/')
                    self.assertEqual(0, (await client.get(origin + '/api/state')).json()['count'])
                with self.assertRaises(ValueError):
                    await workspace.publish(session, preview['revision'], '', False)
                with self.assertRaises(ValueError):
                    await workspace.publish(session, '0' * 64, '', True)
                await workers.close('demo', 'counter', workspace.owner(session))
                self.assertEqual({'saved': True}, await workspace.publish(session, preview['revision'], '', True))
                self.assertEqual(['counter'], [item['name'] for item in bundles.list_tools()])
                published = await dispatch('tools.open', {'project': 'demo', 'name': 'counter'})
                self.assertTrue(published['url'].startswith('http://127.0.0.1:'))
            finally:
                workspace.release(session)
                for key, worker in tuple(workers.items.items()):
                    if worker.project == 'demo' and worker.name == 'counter':
                        await workers.close(worker.project, worker.name, key[2])
