"""Offline consent, revision and acceptance tests; no business files or model calls."""

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from service.chat import agent_usage, ai_chat, model_providers
from service.files import tool_inputs
from service.tools import preview_debug, preview_service


class PreviewDebugTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patches = [patch.dict(os.environ, {'HOME': self.temp.name}),
                   patch.object(model_providers, 'active', return_value=('openai', 'synthetic', {'key': 'model-secret', 'base_url': 'https://example.invalid'})),
                   patch.object(model_providers, 'load', return_value={'connections': {'openai': {'key': 'model-secret'}}}),
                   patch.object(preview_service, '_TMP_DIR', self.root / 'previews'),
                   patch.object(preview_service, '_PREVIEW_META_DIR', self.root / 'previews/_meta')]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        ai_chat.save_chat('chat', [{'role': 'user', 'content': 'Synthetic preview'}])
        self.preview = preview_service.create_temporary_preview('api_key = "tool-secret"\ndef main():\n    pass\n')
        self.path = preview_service.get_preview_file(self.preview['key'])
        self.context = tool_inputs.create('chat', self.preview['key'], [], tool_key='tool:demo/synthetic')
        self.url = self.preview['preview_url'] + '?context=' + self.context
        ai_chat.remember_preview('chat', self.url)
        self.client = SimpleNamespace(has_socket_connection=True, on_disconnect=MagicMock(), on_delete=MagicMock())
        self.page = {'text': 'Ready 0', 'elements': [{'id': 'e1', 'tag': 'button', 'label': 'Increment', 'enabled': True, 'editable': False}], 'media': [], 'horizontal_overflow': False}
        self.client.run_javascript = AsyncMock(return_value=self.page)
        self.run = SimpleNamespace(id=uuid4().hex, project='demo', name='synthetic', preview_key=self.preview['key'], logger=MagicMock())
        self.session = preview_debug.register(self.run, 'chat', self.context, self.client)
        self.addCleanup(preview_debug._sessions.clear)
        self.confirm = AsyncMock(return_value=True)

    async def test_no_reads_before_explicit_authorization(self):
        with self.assertRaises(ValueError):
            await self.session.snapshot()
        self.client.run_javascript.assert_not_awaited()
        self.session.grant(self.confirm)
        result = await self.session.snapshot()
        self.assertEqual('preview', result['source'])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), result['revision'])
        self.assertFalse(result['screenshot'])

    async def test_source_change_revokes_access_and_prevents_click(self):
        self.session.grant(self.confirm)
        self.path.write_text('def main():\n    return "changed"\n')
        with self.assertRaises(ValueError):
            await preview_debug.interact(self.session, element_id='e1', action='click', reason='Synthetic check')
        self.confirm.assert_not_awaited()
        self.assertEqual(0, self.session.approved_at)

    async def test_decline_never_dispatches_and_approval_is_per_action(self):
        self.confirm.return_value = False
        self.session.grant(self.confirm)
        result = await preview_debug.interact(self.session, element_id='e1', action='click', reason='Synthetic check')
        self.assertEqual('user_declined', result['status'])
        self.assertFalse(any('operate(' in call.args[0] for call in self.client.run_javascript.await_args_list))
        self.confirm.return_value = True
        self.client.run_javascript.side_effect = [self.page, {'dispatched': True}]
        result = await preview_debug.interact(self.session, element_id='e1', action='click', reason='Synthetic check')
        self.assertFalse(result['runtime_verified'])
        self.assertEqual(2, self.confirm.await_count)
        request = self.confirm.await_args.args[0]
        self.assertEqual('demo/synthetic', request['tool'])

    async def test_change_while_confirmation_is_open_prevents_dispatch(self):
        async def confirm(request):
            self.path.write_text('def main():\n    return "new version"\n')
            return True
        self.session.grant(confirm)
        with self.assertRaises(ValueError):
            await preview_debug.interact(self.session, element_id='e1', action='click', reason='Synthetic check')
        self.assertEqual(1, self.client.run_javascript.await_count)

    async def test_foreign_chat_or_target_cannot_inspect(self):
        self.session.grant(self.confirm)
        with self.assertRaises(ValueError):
            preview_debug.authorized('chat', 'other', 'synthetic')
        ai_chat.save_chat('other', [{'role': 'user', 'content': 'Other'}])
        ai_chat.remember_preview('other', self.url)
        with self.assertRaises(ValueError):
            preview_debug.authorized('other', 'demo', 'synthetic')

    async def test_diagnostics_bounded_and_credentials_filtered(self):
        self.session.capture({'kind': 'javascript_error', 'message': 'model-secret tool-secret token=abc', 'stack': 'http://localhost/error?context=opaque', 'body': 'not allowed'})
        self.assertNotIn('body', self.session.events[0])
        for _ in range(60):
            self.session.capture({'kind': 'console_error', 'message': 'synthetic'})
        self.assertEqual(40, len(self.session.events))
        serialized = str(self.session.events) + str(self.run.logger.warning.call_args_list)
        for secret in ('model-secret', 'tool-secret', 'opaque', 'token=abc'):
            self.assertNotIn(secret, serialized)
        self.session.grant(self.confirm)
        self.client.run_javascript.return_value = {**self.page, 'text': 'model-secret tool-secret', 'input_values': ['private']}
        snapshot = await self.session.snapshot()
        self.assertNotIn('input_values', snapshot['untrusted_page'])
        self.assertNotIn('tool-secret', str(snapshot))

    async def test_actions_are_bounded_and_pending_actions_not_duplicated(self):
        self.session.grant(self.confirm)
        for action in ('eval', 'navigate', 'reload'):
            with self.assertRaises(ValueError):
                await preview_debug.interact(self.session, element_id='e1', action=action, reason='Synthetic')
        async with self.session.action_lock:
            result = await preview_debug.interact(self.session, element_id='e1', action='click', reason='Synthetic')
            self.assertEqual('action_confirmation_pending', result['status'])
        self.confirm.assert_not_awaited()

    async def test_acceptance_proves_only_declared_checks(self):
        self.session.grant(self.confirm)
        self.session.capture({'kind': 'javascript_error', 'message': 'Synthetic error'})
        result = await preview_debug.verify(self.session, [{'kind': 'text_visible', 'text': 'Ready'}, {'kind': 'no_frontend_errors'}, {'kind': 'no_horizontal_overflow'}])
        self.assertEqual([True, False, True], [c['passed'] for c in result['checks']])
        self.assertEqual('checks_failed', result['status'])
        agent_usage.record_checks('run', self.session.revision, result)
        self.assertEqual('checks_failed', agent_usage.summary('run')['runtime_verification'])
        self.assertNotIn('Ready', str(agent_usage.summary('run')))

    async def test_media_acceptance_requires_observed_time_progress(self):
        self.session.grant(self.confirm)
        self.client.run_javascript.side_effect = [
            {**self.page, 'media': [{'id': 'e2', 'paused': False, 'current_time': 1, 'error_code': None}]},
            {**self.page, 'media': [{'id': 'e2', 'paused': False, 'current_time': 1.5, 'error_code': None}]},
        ]
        with patch.object(preview_debug.asyncio, 'sleep', new=AsyncMock()):
            result = await preview_debug.verify(self.session, [{'kind': 'media_time_advances', 'element_id': 'e2'}])
        self.assertTrue(result['checks'][0]['passed'])
        self.assertIn('audible-output', result['scope'])

    async def test_missing_probe_or_overflow_measurement_is_not_pass(self):
        self.session.grant(self.confirm)
        self.client.run_javascript.return_value = {'error': 'not mounted'}
        with self.assertRaises(ValueError):
            await preview_debug.verify(self.session, [{'kind': 'no_frontend_errors'}])
        self.client.run_javascript.return_value = {'text': 'Ready', 'elements': []}
        result = await preview_debug.verify(self.session, [{'kind': 'no_horizontal_overflow'}])
        self.assertFalse(result['checks'][0]['passed'])

    async def test_disconnect_and_model_change_revoke_authorization(self):
        self.session.grant(self.confirm)
        self.client.on_disconnect.call_args.args[0]()
        with self.assertRaises(ValueError):
            await self.session.snapshot()
        self.session.grant(self.confirm)
        with patch.object(model_providers, 'active', return_value=('openai', 'changed', {'key': 'other'})), self.assertRaises(ValueError):
            await self.session.snapshot()

    async def test_real_agent_confirms_action_and_records_partial_acceptance(self):
        from tests import test_deep_agent as harness
        self.requests = []
        self.session.grant(self.confirm)
        async def javascript(command, **kwargs):
            if 'operate(' in command:
                self.page['text'] = 'Ready 1'
                return {'dispatched': True, 'verified': False}
            return self.page.copy()
        self.client.run_javascript.side_effect = javascript
        def script(data, n):
            args = {'project': 'demo', 'name': 'synthetic'}
            if n == 1:
                return harness.call('inspect_preview', args, 'inspect')
            if n == 2:
                return harness.call('interact_preview', {**args, 'element_id': 'e1', 'action': 'click', 'reason': 'Increment synthetic counter'}, 'click')
            if n == 3:
                return harness.call('verify_preview', {**args, 'checks': [{'kind': 'text_visible', 'text': 'Ready 1'}]}, 'verify')
            return harness.answer('The observed counter check passed.')
        messages = ai_chat.read_chat('chat')
        with harness.DeepAgentTests.transport(self, script):
            events = [event async for event in ai_chat.respond(messages, chat_id='chat')]
        self.confirm.assert_awaited_once()
        self.assertIn(('text', 'The observed counter check passed.'), events)
        result = agent_usage.summary(messages[0]['agent_checkpoint_id'])
        self.assertEqual('partial_checks_passed', result['runtime_verification'])
        self.assertEqual(self.session.revision, result['preview_check_revision'])

    async def test_multiple_live_previews_are_not_guessed(self):
        second = SimpleNamespace(id=uuid4().hex, project='demo', name='synthetic', preview_key=self.preview['key'], logger=MagicMock())
        preview_debug.register(second, 'chat', self.context, self.client)
        with self.assertRaises(ValueError):
            preview_debug.current('chat', self.url)
