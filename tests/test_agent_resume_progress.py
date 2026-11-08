"""Synthetic checkpoint recovery and bounded investigation regressions."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from service.chat import agent_model, agent_runtime, ai_chat, model_providers
from service.tools import ui_presets


class ProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_pages_warn_then_pause(self):
        guard = agent_runtime.NoProgressMiddleware()
        state = {'messages': []}
        hints = []
        for index in range(15):
            state['messages'].extend([
                AIMessage(content='', tool_calls=[{'name': 'read_tool_file', 'args': {'project': 'demo', 'name': 'counter', 'offset': index}, 'id': str(index)}]),
                ToolMessage(content=json.dumps({'path': 'backend/main.py', 'file_fingerprint': 'same', 'total_lines': 100, 'lines': [{'line': 1, 'text': 'same source'}]}), tool_call_id=str(index)),
            ])
            if index == 14:
                with self.assertRaises(agent_model.PublicAgentError):
                    await guard.abefore_model(state, None)
            else:
                hint = await guard.abefore_model(state, None)
                if hint:
                    hints.append(hint)
        self.assertEqual(1, len(hints))

    async def test_distinct_source_pages_are_progress_and_writes_reset_coverage(self):
        guard = agent_runtime.NoProgressMiddleware()
        state = {'messages': []}
        for index in range(20):
            state['messages'].extend([
                AIMessage(content='', tool_calls=[{'name': 'read_tool_file', 'args': {'project': 'demo', 'name': 'counter'}, 'id': str(index)}]),
                ToolMessage(content=json.dumps({'path': 'backend/main.py', 'file_fingerprint': 'same', 'total_lines': 21, 'lines': [{'line': index+1, 'text': 'source'}]}), tool_call_id=str(index)),
            ])
            self.assertIsNone(await guard.abefore_model(state, None))
        state['messages'].extend([
            AIMessage(content='', tool_calls=[{'name': 'write_tool_file', 'args': {}, 'id': 'write'}]),
            ToolMessage(content='{"success":true}', tool_call_id='write'),
        ])
        await guard.abefore_model(state, None)
        self.assertEqual({}, guard.pages)

    async def test_completed_context_keeps_fresh_read_visible_to_model(self):
        messages = [HumanMessage(content='Repair current source', id='user')]
        for index in range(3):
            messages.extend([
                AIMessage(content='', id=f'call-{index}', tool_calls=[{'name': 'read_tool_file', 'args': {'project': 'demo', 'name': 'tool', 'path': 'frontend/App.vue'}, 'id': str(index)}]),
                ToolMessage(content='const current = true;\n' * 4000, tool_call_id=str(index), id=f'read-{index}'),
            ])
        change = await agent_runtime.CompletedContextMiddleware().abefore_model({'messages': messages}, None)
        current = next(item for item in change['messages'] if item.id == 'read-2')
        self.assertTrue(current.content.startswith('const current = true;'))
        self.assertIn('offset=', current.content)
        self.assertNotIn('read omitted', current.content)
        self.assertEqual('const current = true;\n' * 4000, messages[-1].content)

    async def test_completed_payload_compaction_preserves_pending_code_and_metadata(self):
        messages = [
            AIMessage(content='', id='written', tool_calls=[{'name': 'write_tool', 'args': {'files': {'frontend/App.vue': 'x' * 80000}}, 'id': 'done'}]),
            ToolMessage(content='{"revision":"saved"}', tool_call_id='done', id='receipt'),
            AIMessage(content='', id='pending', tool_calls=[{'name': 'write_tool_file', 'args': {'content': 'pending source'}, 'id': 'pending-call'}]),
        ]
        change = await agent_runtime.CompletedContextMiddleware().abefore_model({'messages': messages}, None)
        self.assertEqual('written', change['messages'][0].id)
        self.assertLess(len(json.dumps(change['messages'][0].tool_calls)), 1000)
        self.assertFalse(any(item.id == 'pending' for item in change['messages']))
        self.assertEqual('x' * 80000, messages[0].tool_calls[0]['args']['files']['frontend/App.vue'])

    async def test_budget_resume_skips_history_preparation_and_keeps_real_files(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HOME': home}):
            ai_chat.save_chat('synthetic', [{'role': 'user', 'content': 'Create CRM'}])
            packets = []
            def handle(request):
                packet = json.loads(request.content)
                packets.append(packet)
                results = [m for m in packet['messages'] if m['role'] == 'tool']
                if not results:
                    delta = {'tool_calls': [{'index': 0, 'id': 'write', 'function': {'name': 'write_tool_file', 'arguments': json.dumps({'project': 'demo', 'name': 'crm', 'path': 'backend/helpers.py', 'content': 'saved progress'})}}]}
                    finish = 'tool_calls'
                elif len(results) == 1:
                    delta = {'tool_calls': [{'index': 0, 'id': 'read', 'function': {'name': 'read_tool_file', 'arguments': json.dumps({'project': 'demo', 'name': 'crm', 'path': 'backend/helpers.py'})}}]}
                    finish = 'tool_calls'
                else:
                    self.assertEqual(2, len(results))
                    self.assertIn('saved progress', results[-1]['content'])
                    delta, finish = {'content': 'Continued from saved progress.'}, 'stop'
                return httpx.Response(200, text='data: ' + json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]}) + '\n\ndata: [DONE]\n\n')
            original = httpx.AsyncClient
            with patch.object(model_providers, 'active', return_value=('openai', 'synthetic', {'key': 'synthetic-only', 'base_url': 'https://example.invalid'})), patch.object(agent_model.httpx, 'AsyncClient', side_effect=lambda **kwargs: original(transport=httpx.MockTransport(handle))), patch.object(agent_runtime, 'MODEL_CALLS_PER_RUN', 1):
                with self.assertRaises(agent_model.PublicAgentError):
                    _ = [event async for event in ai_chat.respond(ai_chat.read_chat('synthetic'), 'synthetic')]
                # An oversized saved history used to fail before checkpoint lookup.
                with patch('service.chat.chat_context.prepare', side_effect=AssertionError('Resume must not rebuild history')), patch.object(agent_runtime, 'MODEL_CALLS_PER_RUN', 2):
                    events = [event async for event in ai_chat.respond(ai_chat.read_chat('synthetic'), 'synthetic')]
            self.assertEqual(3, len(packets))
            self.assertIn(('activity', 'resuming'), events)
            self.assertTrue(ai_chat.read_chat('synthetic')[0]['agent_completed'])

    def test_large_references_compact_but_failed_diagnostics_survive(self):
        from service.chat.chat_context import prepare
        messages = [{'role': 'user', 'content': 'Preserve my UI and finish CRM'}]
        for index, (name, content) in enumerate([
            ('read_ui_reference', 'contract ' * 10000),
            ('read_component_api', json.dumps({'component': 'el-table', 'version': 'pinned', 'files': [{'declarations': 'types ' * 12000}]})),
            ('read_ui_preset', json.dumps({'error': 'request_rejected', 'message': 'retain failure'})),
        ]):
            messages.extend([
                {'role': 'assistant', 'content': None, 'tool_calls': [{'id': str(index), 'type': 'function', 'function': {'name': name, 'arguments': '{}'}}]},
                {'role': 'tool', 'tool_call_id': str(index), 'content': content},
            ])
        compact = prepare(messages)
        self.assertLess(len(json.dumps(compact)), 60000)
        self.assertEqual(messages[-1], compact[-1])
        api = next(m for m in compact if m.get('tool_call_id') == '1')
        self.assertEqual('pinned', json.loads(api['content'])['version'])

    def test_ui_preset_display_name_resolves_canonical_pack(self):
        self.assertEqual('compact', ui_presets.reference('紧凑数据')['id'])
        self.assertEqual('compact', ui_presets.reference('Compact')['id'])
        with self.assertRaises(ValueError):
            ui_presets.reference('../outside')
