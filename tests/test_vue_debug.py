"""Consent, revision, page and log boundaries for the browser bridge."""

import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core import tool_run_logs
from service.chat import ai_chat
from service.tools import bundle_debug as debug
from service.tools import tool_bundles as bundles
from service.tools.tool_workers import workers
from tests.test_vue_workspace import fixture


class DebugTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'HOME': self.temp.name}); env.start(); self.addCleanup(env.stop)
        ai_chat.save_chat('chat', [])
        self.files = fixture(); bundles.write('demo', 'counter', self.files, chat_id='chat')
        self.run = tool_run_logs.start('demo', 'counter', preview_key='chat')
        self.addCleanup(self.run.close)
        self.worker = SimpleNamespace(project='demo', name='counter', revision=bundles.revision(self.files), process=SimpleNamespace(poll=lambda: None), log_run=self.run)
        self.key = workers.key('demo', 'counter', 'chat'); workers.items[self.key] = self.worker
        self.addCleanup(lambda: workers.items.pop(self.key, None))
        self.addCleanup(debug.grants.clear); self.addCleanup(debug.pending.clear)
        self.addCleanup(lambda: debug.release_logs('chat'))
        self.page = {'page': 'page-one', 'text': 'Count: 0', 'elements': [{'id': 'e1', 'label': 'Increment', 'tag': 'button', 'enabled': True}], 'media': [], 'horizontal_overflow': False, 'events': []}
        async def request(worker, operation, payload=None):
            return dict(self.page) if operation == 'snapshot' else {'dispatched': True, 'verified': False}
        for item in [patch.object(debug, 'fingerprint', return_value='model-one'), patch.object(debug, 'request', side_effect=request), patch.object(workers, 'status', new=AsyncMock(return_value={'running': False}))]:
            item.start(); self.addCleanup(item.stop)

    async def test_inspection_requires_explicit_grant_and_same_model(self):
        with self.assertRaises(ValueError):
            await debug.inspect('chat', 'demo', 'counter')
        await debug.grant('chat', 'demo', 'counter')
        self.assertEqual('Count: 0', (await debug.inspect('chat', 'demo', 'counter', 'model-one'))['untrusted_page']['text'])
        with self.assertRaises(ValueError):
            await debug.inspect('chat', 'demo', 'counter', 'model-two')

    async def test_source_edit_and_page_reload_each_revoke_access(self):
        await debug.grant('chat', 'demo', 'counter')
        self.page['page'] = 'page-two'
        with self.assertRaises(ValueError):
            await debug.inspect('chat', 'demo', 'counter')
        await debug.grant('chat', 'demo', 'counter')
        bundles.write('demo', 'counter', {**self.files, 'frontend/App.vue': '<template>New UI</template>'}, self.worker.revision, 'chat')
        with self.assertRaises(ValueError):
            await debug.inspect('chat', 'demo', 'counter')

    async def test_action_waits_for_individual_confirmation_and_decline_never_operates(self):
        await debug.grant('chat', 'demo', 'counter')
        task = asyncio.create_task(debug.interact('chat', 'demo', 'counter', 'e1', 'click', 'Synthetic counter'))
        await asyncio.sleep(.01)
        request = debug.requests('chat')[0]
        self.assertFalse(task.done())
        debug.confirm('chat', request['id'], False)
        self.assertFalse((await task)['dispatched'])
        self.assertFalse(any(call.args[1] == 'operate' for call in debug.request.await_args_list))

    async def test_approval_does_not_survive_source_change_during_dialog(self):
        await debug.grant('chat', 'demo', 'counter')
        task = asyncio.create_task(debug.interact('chat', 'demo', 'counter', 'e1', 'click', 'Synthetic counter'))
        await asyncio.sleep(.01)
        request = debug.requests('chat')[0]
        bundles.write('demo', 'counter', {**self.files, 'frontend/App.vue': '<template>Changed</template>'}, self.worker.revision, 'chat')
        debug.confirm('chat', request['id'], True)
        with self.assertRaises(ValueError):
            await task
        self.assertFalse(any(call.args[1] == 'operate' for call in debug.request.await_args_list))

    async def test_granted_log_window_is_bounded_redacted_and_invalidated_on_change(self):
        self.run.writer.write('Traceback synthetic token=private\nbackend/main.py:4\nValueError: failure\n')
        debug.approve_logs('chat', 'demo', 'counter')
        result = debug.read_logs('chat', 'demo', 'counter', limit=2, query='synthetic', model_identity='model-one')
        self.assertNotIn('token=private', str(result))
        self.assertLessEqual(len(result['untrusted_lines']), 2)
        self.run.writer.write('A newer failure\n')
        with self.assertRaises(ValueError):
            debug.read_logs('chat', 'demo', 'counter')

    async def test_other_chat_or_tool_cannot_use_grant(self):
        await debug.grant('chat', 'demo', 'counter')
        for chat, project, name in [('other', 'demo', 'counter'), ('chat', 'demo', 'other')]:
            with self.assertRaises(ValueError):
                await debug.inspect(chat, project, name)
