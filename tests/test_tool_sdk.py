"""Persistent file results, input freezing and safe batch cancellation."""

import asyncio
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

from service.tools.tool_sdk import ToolSDK


class SDKTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'HOME': self.temp.name, 'USERPROFILE': self.temp.name}); env.start(); self.addCleanup(env.stop)
        self.sdk = ToolSDK('demo', 'files')


    async def test_inputs_append_remove_and_reject_changed_snapshots(self):
        one = await self.sdk.upload_input(UploadFile(io.BytesIO(b'one'), filename='one.txt'))
        two = await self.sdk.upload_input(UploadFile(io.BytesIO(b'two'), filename='two.txt'))
        self.assertEqual(2, len(self.sdk.inputs()))
        path = self.sdk.input_path(one['id']); path.write_text('changed')
        with self.assertRaises(ValueError):
            self.sdk.input_path(one['id'])
        self.sdk.remove_input(two['id'])
        self.assertEqual(1, len(self.sdk.inputs()))

    async def test_results_survive_new_runtime_and_do_not_overwrite_source(self):
        source = self.sdk.data_dir / 'source.txt'; source.write_text('keep')
        path = self.sdk.output_path('report.txt'); path.write_text('result')
        result = self.sdk.add_result(path)
        other = ToolSDK('demo', 'files')
        self.assertEqual('report.txt', other.results()[0]['name'])
        self.assertEqual('result', other.outputs.path(result['id']).read_text())
        self.assertEqual('keep', source.read_text())
        with self.assertRaises(ValueError):
            self.sdk.add_result(source)

    async def test_cancellation_finishes_current_item_and_freezes_inputs(self):
        started, finish = asyncio.Event(), asyncio.Event()
        values = []
        async def handle(value):
            started.set(); await finish.wait(); values.append(value)
        self.sdk.start_batch([1, 2], handle)
        await started.wait()
        with self.assertRaises(HTTPException):
            await self.sdk.upload_input(UploadFile(io.BytesIO(b'blocked'), filename='no.txt'))
        with self.assertRaises(HTTPException):
            self.sdk.start_batch([3], handle)
        self.sdk.cancel(); finish.set(); await self.sdk.task
        self.assertEqual([1], values)
        self.assertEqual('cancelled', self.sdk.status()['status'])

    async def test_persistent_sqlite_settings_and_key_validation(self):
        self.sdk.set_setting('table', {'limit': 10})
        self.assertEqual({'limit': 10}, ToolSDK('demo', 'files').get_setting('table'))
        self.assertEqual(20, self.sdk.get_setting('missing', 20))
        self.assertIsNone(self.sdk.get_setting('missing'))
        with self.assertRaises(ValueError):
            self.sdk.set_setting('', {})

    async def test_sync_route_can_start_batch_on_runtime_loop(self):
        self.sdk.loop = asyncio.get_running_loop()
        completed = []
        async def handle(value):
            completed.append(value)
        await asyncio.to_thread(self.sdk.start_batch, [1, 2], handle)
        await asyncio.wrap_future(self.sdk.task)
        self.assertEqual([1, 2], completed)

    async def test_publication_lock_prevents_new_jobs(self):
        from starlette.requests import Request
        self.sdk.host_token = 'host-only'
        request = Request({'type': 'http', 'headers': [(b'x-calabash-host', b'host-only')]})
        self.sdk.publication_lock(True, request)
        with self.assertRaises(HTTPException):
            self.sdk.start_batch([], lambda value: None)
        self.sdk.publication_lock(False, request)

    async def test_selected_media_supports_bounded_range_requests(self):
        import httpx
        from fastapi import FastAPI
        item = await self.sdk.upload_input(UploadFile(io.BytesIO(b'RIFFsynthetic-wave'), filename='sound.wav'))
        app = FastAPI(); app.include_router(self.sdk.router, prefix='/api/sdk')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get(f'/api/sdk/inputs/{item["id"]}/content', headers={'Range': 'bytes=0-3'})
        self.assertEqual(206, response.status_code)
        self.assertEqual(b'RIFF', response.content)
