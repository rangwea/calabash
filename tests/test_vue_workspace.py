"""Synthetic Vue migration acceptance: no user files, models or installed App."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from service.tools import tool_bundles as bundles


def fixture(name='counter'):
    return {
        'tool.json': json.dumps({'format': 'calabash-vue-tool', 'version': 1, 'project': 'demo', 'name': name, 'title': 'Counter'}),
        'frontend/App.vue': '<script setup>import {ref} from "vue";const n=ref(0)</script><template><h1>Count: {{n}}</h1><el-button @click="n++">Increment</el-button></template>',
        'backend/main.py': 'def setup(app, sdk):\n    @app.get("/api/state")\n    def state():\n        return {"count": 0}\n',
    }


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'HOME': self.temp.name})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_index_only_includes_current_bundle_format(self):
        files = fixture()
        bundles.write('demo', 'counter', files)
        unrelated = bundles.directory('demo', 'single_file').with_suffix('.py')
        unrelated.write_text("raise RuntimeError('Must not execute')")
        self.assertEqual(['counter'], [tool['name'] for tool in bundles.list_tools()])
        with self.assertRaises(bundles.ToolUnavailable) as error:
            bundles.read('demo', 'single_file')
        self.assertEqual('tool_not_found', error.exception.code)

    def test_atomic_versions_preserve_current_source_on_conflict(self):
        files = fixture()
        first = bundles.write('demo', 'counter', files)
        changed = {**files, 'frontend/App.vue': '<template>Changed</template>'}
        with self.assertRaises(ValueError):
            bundles.write('demo', 'counter', changed)
        self.assertEqual(files, bundles.read('demo', 'counter')['files'])
        second = bundles.write('demo', 'counter', changed, first['revision'])
        self.assertNotEqual(first['revision'], second['revision'])

    def test_draft_does_not_replace_published_source(self):
        files = fixture(); bundles.write('demo', 'counter', files)
        changed = {**files, 'frontend/App.vue': '<template>Draft</template>'}
        bundles.write('demo', 'counter', changed, chat_id='chat')
        self.assertEqual(files, bundles.read('demo', 'counter')['files'])
        self.assertEqual(changed, bundles.read('demo', 'counter', 'chat')['files'])

    def test_archive_roundtrip_does_not_execute_backend(self):
        files = fixture(); bundles.write('demo', 'counter', files)
        data = bundles.export_zip('demo', 'counter')
        self.assertEqual(files, bundles.inspect_zip(data))

    def test_rejects_paths_scripts_symlinks_and_duplicate_zip_entries(self):
        for path in ['../tool.json', '/tool.json', 'frontend/../x.vue', 'frontend\\x.vue', 'package.json', 'frontend/node_modules/x.ts']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                bundles.safe_path(path)
        path = bundles.directory('demo', 'counter')
        path.parent.mkdir(parents=True)
        path.symlink_to(Path(self.temp.name), target_is_directory=True)
        with self.assertRaises(ValueError):
            bundles.read('demo', 'counter')

    def test_invalid_manifest_or_backend_rejected_before_write(self):
        for key, value in [('tool.json', '{}'), ('backend/main.py', 'def setup(app,sdk) pass'), ('backend/main.py', 'def main(): pass')]:
            with self.subTest(key=key), self.assertRaises((ValueError, SyntaxError)):
                bundles.write('demo', 'counter', {**fixture(), key: value})
        self.assertFalse(bundles.directory('demo', 'counter').exists())


class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'HOME': self.temp.name})
        self.env.start(); self.addCleanup(self.env.stop)
        from core.workspace_app import create_workspace_app
        from service.chat.chat_runs import runs
        self.runs = runs; self.runs.runs.clear()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_workspace_app()), base_url='http://127.0.0.1')
        await self.client.get('/')
        self.client.headers['X-Calabash-Request'] = 'workspace'

    async def asyncTearDown(self):
        from service.tools.tool_checks import checks
        await checks.close()
        await self.runs.close()
        await self.client.aclose()

    async def test_session_origin_and_request_marker_are_enforced(self):
        response = await self.client.get('/api/workspace/chats', headers={'Origin': 'https://evil.invalid'})
        self.assertEqual(403, response.status_code)
        response = await self.client.get('/api/workspace/chats', headers={'Host': 'evil.invalid'})
        self.assertEqual(403, response.status_code)
        self.client.cookies.clear()
        self.assertEqual(403, (await self.client.get('/api/workspace/chats')).status_code)

    async def test_chat_lifecycle_and_secret_free_settings(self):
        from service.chat import model_providers
        model_providers.save({'selected': 'openai::synthetic', 'connections': {'openai': {'key': 'never-return-this', 'base_url': 'https://example.invalid', 'models': ['synthetic']}}})
        settings = await self.client.get('/api/workspace/settings/models')
        self.assertNotIn('never-return-this', settings.text)
        response = await self.client.post('/api/workspace/chats')
        self.assertEqual(201, response.status_code)
        chat_id = response.json()['id']
        self.assertEqual(200, (await self.client.get(f'/api/workspace/chats/{chat_id}')).status_code)
        await self.client.patch(f'/api/workspace/chats/{chat_id}', json={'title': 'Synthetic'})
        self.assertEqual([], (await self.client.get('/api/workspace/chats')).json())
        from service.chat import ai_chat
        ai_chat.save_chat(chat_id, [{'role': 'user', 'content': 'Hello'}])
        self.assertEqual('Synthetic', (await self.client.get('/api/workspace/chats')).json()[0]['title'])

    async def test_default_ui_is_a_configurable_catalog_selection(self):
        data=(await self.client.get('/api/workspace/bootstrap')).json()
        self.assertEqual({'office','compact','soft'}, {p['id'] for p in data['ui_presets']})
        self.assertEqual(200,(await self.client.patch('/api/workspace/settings',json={'default_ui':'soft'})).status_code)
        self.assertEqual('soft',(await self.client.get('/api/workspace/bootstrap')).json()['default_ui'])
        self.assertEqual(409,(await self.client.patch('/api/workspace/settings',json={'default_ui':'../outside'})).status_code)
        self.assertEqual('soft',(await self.client.get('/api/workspace/bootstrap')).json()['default_ui'])

    async def test_blank_chat_enters_recent_only_after_first_message(self):
        from service.chat import ai_chat
        chat = (await self.client.post('/api/workspace/chats')).json()['id']
        self.assertEqual([], (await self.client.get('/api/workspace/chats')).json())
        self.assertEqual(200, (await self.client.get(f'/api/workspace/chats/{chat}')).status_code)
        async def fake(messages, chat_id):
            yield 'text', 'Synthetic reply'
        with patch.object(ai_chat, 'respond', fake):
            response = await self.client.post(f'/api/workspace/chats/{chat}/runs', json={'text': 'My first request'})
            self.assertEqual(202, response.status_code)
            recent = (await self.client.get('/api/workspace/chats')).json()
            self.assertEqual([chat], [row['id'] for row in recent])
            await self.runs.get(chat).task

    async def test_parallel_chats_cancellation_and_event_replay(self):
        from service.chat import ai_chat
        async def fake(messages, chat_id):
            yield 'text', 'First'
            await asyncio.sleep(.05)
            yield 'text', 'Second'
        first = (await self.client.post('/api/workspace/chats')).json()['id']
        second = (await self.client.post('/api/workspace/chats')).json()['id']
        with patch.object(ai_chat, 'respond', fake):
            for chat in (first, second):
                self.assertEqual(202, (await self.client.post(f'/api/workspace/chats/{chat}/runs', json={'text': 'Synthetic'})).status_code)
            self.assertEqual(409, (await self.client.post(f'/api/workspace/chats/{first}/runs', json={'text': 'Duplicate'})).status_code)
            await asyncio.sleep(.01)
            await self.client.post(f'/api/workspace/chats/{first}/cancel')
            await asyncio.sleep(.07)
            self.assertEqual('cancelled', self.runs.get(first).status)
            self.assertEqual('completed', self.runs.get(second).status)
            response = await self.client.get(f'/api/workspace/chats/{second}/events?after=1')
            self.assertNotIn('First', response.text)
            self.assertIn('Second', response.text)
            self.assertIn('completed', response.text)

    async def test_preview_check_and_publication_share_verified_build(self):
        from service.tools.tool_checks import checks
        chat = (await self.client.post('/api/workspace/chats')).json()['id']
        source = bundles.write('demo', 'counter', fixture(), chat_id=chat)
        calls = []
        async def build(files):
            calls.append(files)
            root = Path(self.temp.name) / '.calabash/builds/verified'
            (root / 'dist').mkdir(parents=True)
            (root / 'dist/index.html').write_text('verified-build')
            return root
        path = '/api/workspace/tools/demo/counter'
        with patch('service.tools.tool_checks.build_bundle', build):
            state = await self.client.post(path + '/preview/check', json={'chat_id': chat})
            self.assertEqual('checking', state.json()['state'])
            await asyncio.gather(*(entry.task for entry in checks.entries.values()))
            state = await self.client.post(path + '/preview/check', json={'chat_id': chat})
            self.assertEqual('passed', state.json()['state'])
            self.assertEqual(source['revision'], state.json()['revision'])
            published = await self.client.post(path + '/publish', json={'chat_id': chat, 'revision': source['revision'], 'confirmed': True})
            self.assertEqual(200, published.status_code, published.text)
            self.assertEqual(1, len(calls))
            self.assertEqual('verified-build', (bundles.directory('demo', 'counter') / 'dist/index.html').read_text())
            changed = {**fixture(), 'frontend/App.vue': '<template>Changed</template>'}
            bundles.write('demo', 'counter', changed, source['revision'], chat_id=chat)
            stale = await self.client.post(path + '/publish', json={'chat_id': chat, 'revision': source['revision'], 'confirmed': True})
            self.assertEqual(409, stale.status_code)
            self.assertEqual(1, len(calls))

    async def test_source_changed_during_build_cannot_publish(self):
        chat = (await self.client.post('/api/workspace/chats')).json()['id']
        source = bundles.write('demo', 'counter', fixture(), chat_id=chat)
        async def build(files):
            updated = {**files, 'frontend/App.vue': '<template>Updated during build</template>'}
            bundles.write('demo', 'counter', updated, source['revision'], chat_id=chat)
            root = Path(self.temp.name) / '.calabash/builds/race'
            (root / 'dist').mkdir(parents=True)
            (root / 'dist/index.html').write_text('outdated')
            return root
        with patch('service.tools.tool_checks.build_bundle', build):
            response = await self.client.post('/api/workspace/tools/demo/counter/publish', json={'chat_id': chat, 'revision': source['revision'], 'confirmed': True})
            self.assertEqual(409, response.status_code)
            self.assertIn('Preview changed during build', response.text)
            self.assertFalse(bundles.directory('demo', 'counter').exists())

    async def test_failed_check_does_not_publish(self):
        from service.tools.tool_workers import FrontendBuildError
        chat = (await self.client.post('/api/workspace/chats')).json()['id']
        source = bundles.write('demo', 'counter', fixture(), chat_id=chat)
        root = Path(self.temp.name) / 'failed'
        root.mkdir()
        (root / 'build.log').write_text('frontend/App.vue(9,4): error TS2322: secret-value')
        async def build(files):
            raise FrontendBuildError(root)
        with patch('service.tools.tool_checks.build_bundle', build):
            response = await self.client.post('/api/workspace/tools/demo/counter/publish', json={'chat_id': chat, 'revision': source['revision'], 'confirmed': True})
            self.assertEqual(409, response.status_code)
            state = await self.client.post('/api/workspace/tools/demo/counter/preview/check', json={'chat_id': chat})
            self.assertEqual('failed', state.json()['state'])
            self.assertNotIn('diagnostics', state.json())
            from service.tools.check_records import read as read_record
            saved = read_record('demo', 'counter', chat, source['revision'])
            self.assertEqual(9, saved['diagnostics'][0]['line'])
            self.assertNotIn('secret-value', state.text)
            self.assertFalse(bundles.directory('demo', 'counter').exists())

    async def test_import_needs_confirmation_and_preserves_existing_revision(self):
        response = await self.client.post('/api/workspace/tools/import', json={'files': fixture(), 'confirmed': False})
        self.assertEqual(409, response.status_code)
        self.assertFalse(bundles.directory('demo', 'counter').exists())


if __name__ == '__main__':
    unittest.main()
