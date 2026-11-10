"""Synthetic AI consent and output safety; never contact a model provider."""
import asyncio
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from service.actions.ai import validated_output
from service.actions.models import AIParameters
from service.actions.office import ActionFailure
from service.tools.tool_sdk import ToolSDK


class AIActionsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {'HOME': temporary.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.sdk = ToolSDK('demo', 'ai', run_id='a' * 32, source_revision='b' * 64)
        self.sdk.host_token = 'synthetic-host'
        self.sdk.loop = asyncio.get_running_loop()
        app = FastAPI()
        app.include_router(self.sdk.router, prefix='/api/sdk')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')
        self.addAsyncCleanup(self.client.aclose)

    async def pending(self):
        for _ in range(100):
            packet = (await self.client.get('/api/sdk/ai/requests', headers={'X-Calabash-Host': 'synthetic-host'})).json()
            if packet:
                return packet[0]
            await asyncio.sleep(.001)
        raise AssertionError('AI request missing')

    async def control(self, pending, operation, **values):
        return await self.client.post('/api/sdk/ai/control', json={'request_id': pending['request_id'], 'digest': pending['digest'], 'operation': operation, **values}, headers={'X-Calabash-Host': 'synthetic-host'})

    async def test_no_result_before_approval_and_five_tasks_deliver_files(self):
        tasks = [('summarize', {}, 'Summary'), ('translate', {'language': 'English'}, 'Translation'), ('generate', {}, 'Generated'),
                 ('classify', {'labels': ['A', 'B']}, '{"label":"A"}'), ('extract', {'fields': {'name': 'string', 'count': 'number'}}, '{"name":"Synthetic","count":2}')]
        for task, extra, output in tasks:
            self.sdk.actions.start('ai.text', {'task': task, 'text': 'Synthetic input', **extra})
            pending = await self.pending()
            self.assertNotIn('payload', pending)
            self.assertEqual([], self.sdk.actions.runs()[0]['result'] or [])
            rejected = await self.control(pending, 'deliver', text=output)
            self.assertEqual(409, rejected.status_code)
            lease = (await self.control(pending, 'begin')).json()['lease']
            self.assertEqual(409, (await self.control(pending, 'begin')).status_code)
            self.assertEqual(200, (await self.control(pending, 'deliver', lease=lease, text=output)).status_code)
            await self.sdk.task
            result = self.sdk.actions.runs()[0]
            self.assertEqual('succeeded', result['status'], result)
            self.assertIsNone(self.sdk.jobs.jobs[0].value.parameters)
            path = self.sdk.outputs.path(result['result']['outputs'][0]['id'])
            if task in {'classify', 'extract'}:
                self.assertEqual(json.loads(output), json.loads(path.read_text()))
            else:
                self.assertEqual(output, path.read_text())
            self.assertEqual(409, (await self.control(pending, 'deliver', lease=lease, text=output)).status_code)

    async def test_host_authorization_and_cancel_leave_no_result(self):
        self.sdk.actions.start('ai.text', {'task': 'summarize', 'text': 'private-synthetic'})
        pending = await self.pending()
        self.assertEqual(403, (await self.client.get('/api/sdk/ai/requests')).status_code)
        response = await self.client.post('/api/sdk/ai/control', json={**pending, 'operation': 'begin'})
        self.assertNotEqual(200, response.status_code)
        self.sdk.cancel()
        await asyncio.gather(self.sdk.task, return_exceptions=True)
        self.assertEqual('cancelled', self.sdk.actions.runs()[0]['status'])
        self.assertEqual([], self.sdk.results())
        self.assertIsNone(self.sdk.jobs.jobs[0].value.parameters)

    async def test_invalid_json_and_rejected_request_do_not_publish_or_log_content(self):
        from core.logger import logger
        sink = io.StringIO()
        identity = logger.add(sink, diagnose=False)
        try:
            self.sdk.actions.start('ai.text', {'task': 'classify', 'text': 'private-synthetic', 'labels': ['A', 'B']})
            pending = await self.pending()
            lease = (await self.control(pending, 'begin')).json()['lease']
            await self.control(pending, 'deliver', lease=lease, text='{"label":"private-invalid-label"}')
            await self.sdk.task
            self.assertEqual('ai_invalid_output', self.sdk.actions.runs()[0]['error']['code'])
            self.assertEqual([], self.sdk.results())
        finally:
            logger.remove(identity)
        self.assertNotIn('private-synthetic', sink.getvalue())
        self.assertNotIn('private-invalid-label', sink.getvalue())

    async def test_expired_or_wrong_digest_and_missing_constraints_fail(self):
        for value in [{'task': 'classify', 'text': 'text'}, {'task': 'extract', 'text': 'text'}, {'task': 'translate', 'text': 'text'}]:
            with self.assertRaises(ActionFailure):
                self.sdk.actions.start('ai.text', value)
        self.sdk.actions.start('ai.text', {'task': 'summarize', 'text': 'text'})
        pending = await self.pending()
        self.assertEqual(409, (await self.control({**pending, 'digest': '0' * 64}, 'begin')).status_code)
        self.sdk.ai.current['expires'] = 0
        self.assertEqual(409, (await self.control(pending, 'begin')).status_code)
        self.sdk.cancel()
        await asyncio.gather(self.sdk.task, return_exceptions=True)

    def test_structured_validation_rejects_extra_duplicate_and_wrong_types(self):
        parameters = AIParameters(task='extract', text='text', fields={'count': 'number'})
        for text in ['{"count":true}', '{"count":1,"extra":2}', '{"count":1,"count":2}', '{"count":NaN}', '```json\n{"count":1}\n```']:
            with self.subTest(text=text), self.assertRaises(ActionFailure):
                validated_output(parameters, text)
