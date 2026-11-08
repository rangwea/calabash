"""Real Agent graph with scripted local model responses and temporary tools."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import httpx

from service.chat import agent_model, agent_runtime, ai_chat, model_providers
from service.chat.source_credentials import SourceCredentials
from service.tools import tool_bundles as bundles
from tests.test_vue_workspace import fixture


class VueAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'HOME': self.temp.name})
        env.start(); self.addCleanup(env.stop)
        ai_chat.save_chat('synthetic', [{'role': 'user', 'content': 'Create and modify a counter, keep its interface'}])
        self.requests = []

    async def test_graph_rejects_context_placeholder_and_continues_with_real_source(self):
        steps = [
            ('write_tool', {'project': 'demo', 'name': 'counter', 'files': fixture()}),
            ('write_tool_file', {'project': 'demo', 'name': 'counter', 'path': 'frontend/App.vue', 'content': '[Executed source snapshot omitted. Read current tool or virtual draft before editing.]'}),
            ('read_tool_file', {'project': 'demo', 'name': 'counter', 'path': 'frontend/App.vue'}),
        ]
        def handle(request):
            packet = json.loads(request.content)
            results = [message for message in packet['messages'] if message['role'] == 'tool']
            if len(results) == 2:
                self.assertIn('source_placeholder_rejected', results[-1]['content'])
            if len(results) == 3:
                self.assertIn('Increment', results[-1]['content'])
            if len(results) < len(steps):
                name, args = steps[len(results)]
                delta = {'tool_calls': [{'index': 0, 'id': f'call-{len(results)}', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
                finish = 'tool_calls'
            else:
                delta, finish = {'content': 'Original source preserved after rejected placeholder.'}, 'stop'
            return httpx.Response(200, text='data: ' + json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]}) + '\n\ndata: [DONE]\n\n')
        original = httpx.AsyncClient
        with patch.object(model_providers, 'active', return_value=('openai', 'synthetic', {'key': 'synthetic-only', 'base_url': 'https://example.invalid'})), patch.object(agent_model.httpx, 'AsyncClient', side_effect=lambda **options: original(transport=httpx.MockTransport(handle))):
            events = [event async for event in ai_chat.respond(ai_chat.read_chat('synthetic'), 'synthetic')]
        self.assertTrue(any(kind == 'preview' for kind, _ in events))
        self.assertEqual(fixture()['frontend/App.vue'], bundles.read('demo', 'counter', 'synthetic')['files']['frontend/App.vue'])

    async def test_missing_and_invalid_file_requests_do_not_abort_generation(self):
        packets = []
        def handle(request):
            packet = json.loads(request.content); packets.append(packet)
            results = [m for m in packet['messages'] if m['role'] == 'tool']
            steps = [
                ('read_tool', {'project': 'demo', 'name': 'absent'}),
                ('write_tool', {'project': 'demo', 'name': 'counter', 'files': fixture()}),
                ('read_tool_file', {'project': 'demo', 'name': 'counter', 'path': 'frontend/missing.vue'}),
            ]
            if len(results) < len(steps):
                name, args = steps[len(results)]
                delta = {'tool_calls': [{'index': 0, 'id': f'recover-{len(results)}', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
                finish = 'tool_calls'
            else:
                self.assertEqual('tool_not_found', json.loads(results[0]['content'])['error'])
                self.assertEqual('unknown_field_or_file', json.loads(results[2]['content'])['error'])
                delta, finish = {'content': 'New Vue draft saved. Retry preview manually.'}, 'stop'
            return httpx.Response(200, text='data: ' + json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]}) + '\n\ndata: [DONE]\n\n')
        original = httpx.AsyncClient
        async def unhandled(self, request, handler):
            return await handler(request)
        with patch.object(model_providers, 'active', return_value=('openai', 'synthetic', {'key': 'synthetic-only', 'base_url': 'https://example.invalid'})), patch.object(agent_model.httpx, 'AsyncClient', side_effect=lambda **kwargs: original(transport=httpx.MockTransport(handle))):
            # Simulate the previously deployed failure, then resume its pending
            # tool call with the corrected middleware and the same checkpoint.
            with patch.object(agent_runtime.ToolRequestMiddleware, 'awrap_tool_call', unhandled), self.assertRaises(bundles.ToolUnavailable):
                _ = [event async for event in ai_chat.respond(ai_chat.read_chat('synthetic'), 'synthetic')]
            events = [event async for event in ai_chat.respond(ai_chat.read_chat('synthetic'), 'synthetic')]
        self.assertEqual(4, len(packets))
        self.assertTrue(any(kind == 'preview' for kind, _ in events))
        self.assertIn('New Vue draft saved', ai_chat.read_chat('synthetic')[-1]['content'])

    async def test_build_check_uses_real_source_without_exposing_credentials(self):
        from pathlib import Path

        from service.chat.bundle_agent_tools import build_tools
        from service.tools.tool_checks import checks
        files = fixture()
        files['frontend/App.vue'] = '<script setup lang="ts">const api_key = "synthetic-secret-value"</script><template>Counter</template>'
        bundles.write('demo', 'counter', files, chat_id='synthetic')
        async def build(actual):
            self.assertEqual(files, actual)
            root = Path(self.temp.name) / '.calabash/builds/check'
            (root / 'dist').mkdir(parents=True)
            (root / 'dist/index.html').write_text('compiled')
            return root
        tools = build_tools('synthetic', [], 'test')
        check = next(tool for tool in tools if tool.name == 'check_tool_build')
        try:
            with patch('service.tools.tool_checks.build_bundle', build):
                value = await check.ainvoke({'project': 'demo', 'name': 'counter'})
            self.assertEqual('passed', json.loads(value)['state'])
            self.assertNotIn('synthetic-secret-value', value)
            read_record = next(tool for tool in tools if tool.name == 'read_build_diagnostics')
            stored = read_record.invoke({'project': 'demo', 'name': 'counter'})
            self.assertEqual('passed', json.loads(stored)['state'])
            self.assertNotIn('synthetic-secret-value', stored)
            changed = {**files, 'frontend/App.vue': '<template>New version</template>'}
            source = bundles.read('demo', 'counter', 'synthetic')
            bundles.write('demo', 'counter', changed, source['revision'], chat_id='synthetic')
            self.assertEqual('unavailable', json.loads(read_record.invoke({'project': 'demo', 'name': 'counter'}))['state'])
        finally:
            await checks.close()

    async def test_selected_ui_is_snapshotted_and_workflow_records_build_evidence(self):
        from pathlib import Path
        ai_chat.save_chat('synthetic', [{'role':'user','content':'@柔和彩色 Create a counter'}])
        packets=[]
        def handle(request):
            packet=json.loads(request.content);packets.append(packet)
            results=[item for item in packet['messages'] if item['role']=='tool']
            steps=[('write_tool',{'project':'demo','name':'counter','files':fixture()}),('check_tool_build',{'project':'demo','name':'counter'})]
            if len(results)<len(steps):
                name,args=steps[len(results)]
                delta={'tool_calls':[{'index':0,'id':f'ui-{len(results)}','function':{'name':name,'arguments':json.dumps(args)}}]}
                finish='tool_calls'
            else:
                self.assertEqual('passed',json.loads(results[-1]['content'])['state'])
                delta,finish={'content':'Please try the preview before saving.'},'stop'
            return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':delta,'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n')
        original=httpx.AsyncClient
        try:
            with patch.object(model_providers,'active',return_value=('openai','synthetic',{'key':'synthetic-only','base_url':'https://example.invalid'})), patch.object(agent_model.httpx,'AsyncClient',side_effect=lambda **kwargs: original(transport=httpx.MockTransport(handle))):
                _=[event async for event in ai_chat.respond(ai_chat.read_chat('synthetic'),'synthetic')]
            source=bundles.read('demo','counter','synthetic')
            self.assertEqual('soft',json.loads(source['files']['tool.json'])['ui']['preset'])
            self.assertIn('--calabash-primary:#7860ad',source['files']['frontend/calabash-theme.css'])
            context=json.loads((Path(self.temp.name)/'.calabash/agent/task_contexts/synthetic.json').read_text())
            self.assertEqual('manual_review',context['phase'])
            self.assertEqual(source['revision'],context['checks']['revision'])
            self.assertFalse(context['runtime_verified'])
            self.assertEqual(3,len(packets))
        finally:
            from service.tools.tool_checks import checks
            await checks.close()

    async def test_graph_creates_patches_and_validates_draft_without_publishing(self):
        files = fixture()
        def handle(request):
            packet = json.loads(request.content); self.requests.append(packet)
            names = {item['function']['name'] for item in packet['tools']}
            self.assertFalse(names & {'execute', 'task'})
            results = [item for item in packet['messages'] if item['role'] == 'tool']
            n = len(results)
            args = None
            if n == 0:
                name, args = 'read_ui_reference', {}
            elif n == 1:
                name, args = 'write_tool', {'project': 'demo', 'name': 'counter', 'files': files}
            elif n == 2:
                name, args = 'read_tool', {'project': 'demo', 'name': 'counter'}
            elif n == 3:
                name, args = 'patch_tool_file', {'project': 'demo', 'name': 'counter', 'path': 'frontend/App.vue', 'old': 'Increment', 'new': 'Increase'}
            elif n == 4:
                name, args = 'validate_tool', {'project': 'demo', 'name': 'counter'}
            delta = {'content': 'Draft saved; refresh and verify manually.'} if args is None else {'tool_calls': [{'index': 0, 'id': f'call-{n}', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
            body = {'choices': [{'delta': delta, 'finish_reason': 'stop' if args is None else 'tool_calls'}]}
            return httpx.Response(200, text='data: ' + json.dumps(body) + '\n\ndata: [DONE]\n\n')
        original_client = httpx.AsyncClient
        def client(*args, **kwargs):
            return original_client(transport=httpx.MockTransport(handle))
        with patch.object(model_providers, 'active', return_value=('openai', 'synthetic', {'key': 'synthetic-only', 'base_url': 'https://example.invalid'})), patch.object(agent_model.httpx, 'AsyncClient', side_effect=client):
            messages = ai_chat.read_chat('synthetic')
            events = [event async for event in ai_chat.respond(messages, 'synthetic')]
        self.assertEqual(6, len(self.requests))
        self.assertIn('Increase', bundles.read('demo', 'counter', 'synthetic')['files']['frontend/App.vue'])
        self.assertFalse(bundles.directory('demo', 'counter').exists())
        self.assertTrue(any(kind == 'manual_preview' for kind, value in events))
        self.assertTrue(ai_chat.remembered_preview('synthetic').startswith('/preview/demo/counter'))
        self.assertIn('Draft saved', ai_chat.read_chat('synthetic')[-1]['content'])
        follow_up = ai_chat.read_chat('synthetic') + [{'role': 'user', 'content': 'Explain the current draft without changing it'}]
        with patch.object(model_providers, 'active', return_value=('openai', 'synthetic', {'key': 'synthetic-only', 'base_url': 'https://example.invalid'})), patch.object(agent_model.httpx, 'AsyncClient', side_effect=client):
            follow_events = [event async for event in ai_chat.respond(follow_up, 'synthetic')]
        self.assertFalse([value for kind, value in follow_events if kind == 'activity' and value != 'generating_tool'])

    def test_credentials_are_private_and_unknown_placeholders_rejected(self):
        secrets = SourceCredentials()
        source = 'const api_key = "synthetic-secret-value";'
        redacted = secrets.redact(source)
        self.assertNotIn('synthetic-secret-value', redacted)
        self.assertEqual(source, secrets.restore(redacted))
        with self.assertRaises(ValueError):
            SourceCredentials().restore(redacted)
