"""Real graph and compiler acceptance using a scripted model and synthetic source."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from service.chat import agent_model, ai_chat, model_providers
from service.tools import tool_bundles as bundles
from service.tools.tool_checks import checks
from tests.test_vue_workspace import fixture


@unittest.skipUnless(shutil.which('node') and Path('node_modules/vue').is_dir(), 'Local frontend compiler required')
class ReadDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_paged_read_then_edit_deliver_and_real_build(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'HOME': temporary}):
            files = fixture()
            body = files['backend/main.py']
            files['backend/main.py'] = body + '# synthetic coverage line\n' * (497 - len(body.splitlines()))
            steps = [
                ('write_tool', {'project': 'demo', 'name': 'counter', 'files': files}),
                *[('read_tool_file', {'project': 'demo', 'name': 'counter', 'path': 'backend/main.py', 'offset': offset, 'limit': 130}) for offset in (0, 130, 260, 390)],
                ('patch_tool_file', {'project': 'demo', 'name': 'counter', 'path': 'backend/main.py', 'old': '"count": 0', 'new': '"count": 1'}),
                ('check_tool_build', {'project': 'demo', 'name': 'counter'}),
            ]
            observed = []
            def handle(request):
                packet = json.loads(request.content)
                messages = packet['messages']
                results = [m for m in messages if m['role'] == 'tool']
                index = len(results)
                if index == 5:
                    self.assertTrue(any('all 497 lines read' in str(m.get('content')) for m in messages))
                if index < len(steps):
                    name, args = steps[index]
                    args = dict(args)
                    observed.append(name)
                    delta = {'tool_calls': [{'index': 0, 'id': f'step-{index}', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
                    finish = 'tool_calls'
                else:
                    self.assertEqual('passed', json.loads(results[-1]['content'])['state'])
                    delta, finish = {'content': 'Synthetic modification built successfully.'}, 'stop'
                return httpx.Response(200, text='data: ' + json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]}) + '\n\ndata: [DONE]\n\n')
            original = httpx.AsyncClient
            ai_chat.save_chat('synthetic', [{'role': 'user', 'content': 'Create counter, inspect then update backend count'}])
            try:
                with patch.object(model_providers, 'active', return_value=('openai', 'synthetic', {'key': 'synthetic-only', 'base_url': 'https://example.invalid'})), patch.object(agent_model.httpx, 'AsyncClient', side_effect=lambda **options: original(transport=httpx.MockTransport(handle))):
                    _ = [event async for event in ai_chat.respond(ai_chat.read_chat('synthetic'), 'synthetic')]
                self.assertIn('"count": 1', bundles.read('demo', 'counter', 'synthetic')['files']['backend/main.py'])
                self.assertEqual([name for name, _ in steps], observed)
            finally:
                await checks.close()
