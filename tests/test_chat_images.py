import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from PIL import Image

from service.chat import (
    agent_model,
    agent_store,
    ai_chat,
    chat_context,
    model_providers,
)
from service.files import chat_images as images
from service.files import conversation_files as files


class ImageFixture:
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for module, field, value in [(ai_chat, 'app_dir', self.root), (ai_chat, 'tools_dir', self.root / 'tools'),
                                     (agent_store, 'app_dir', self.root), (model_providers, 'app_dir', self.root)]:
            patcher = patch.object(module, field, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.path = self.root / 'reference.png'
        Image.new('RGB', (300, 160), 'red').save(self.path)
        self.item = files.register('one', self.path)
        self.messages = [{'role': 'user', 'content': 'Use this design', 'attachments': [self.item['id']]}]
        ai_chat.save_chat('one', self.messages)
        self.connection = {'key': 'fake', 'base_url': 'https://example.test', 'models': ['deepseek-flash']}


class ImageServiceTests(ImageFixture, unittest.TestCase):
    def test_model_gets_real_pixels_and_storage_keeps_only_references(self):
        prepared = images.attach_references(chat_context.prepare(self.messages, 'one'), 'one')
        self.assertIn(images.PREFIX, json.dumps(prepared))
        self.assertNotIn('base64,', json.dumps(prepared))
        wire = images.hydrate(prepared, 'one', 'deepseek', 'deepseek-flash', self.connection)
        url = wire[-1]['content'][1]['image_url']['url']
        with Image.open(io.BytesIO(base64.b64decode(url.split(',', 1)[1]))) as image:
            self.assertEqual((255, 0, 0), image.getpixel((10, 10)))
        self.assertNotIn('base64,', json.dumps(ai_chat.read_chat('one')))
        self.assertIn(images.PREFIX, json.dumps(prepared))

    def test_ownership_unsent_changed_and_deleted_images_are_rejected(self):
        prepared = images.attach_references(chat_context.prepare(self.messages, 'one'), 'one')
        with self.assertRaises(ValueError):
            images.hydrate(prepared, 'other', 'deepseek', 'deepseek-flash', self.connection)
        Image.new('RGB', (300, 160), 'blue').save(self.path)
        with self.assertRaises(ValueError):
            images.hydrate(prepared, 'one', 'deepseek', 'deepseek-flash', self.connection)
        ai_chat.delete_chat('one')
        with self.assertRaises(ValueError):
            images.encode('one', self.item['id'])

    def test_pending_thumbnail_is_local_but_unsent_pixels_cannot_reach_model(self):
        Image.new('RGB', (100, 80), 'blue').save(self.root / 'pending.png')
        pending = files.register('one', self.root / 'pending.png')
        self.assertTrue(images.encode('one', pending['id'], thumbnail=True).startswith('data:image/png;base64,'))
        with self.assertRaises(ValueError):
            images.encode('one', pending['id'])

    def test_unsupported_model_and_external_image_references_fail_explicitly(self):
        prepared = images.attach_references(chat_context.prepare(self.messages, 'one'), 'one')
        with self.assertRaises(ValueError):
            images.hydrate(prepared, 'one', 'deepseek', 'deepseek-chat', self.connection)
        prepared[-1]['content'][1]['image_url']['url'] = 'https://example.test/private.png'
        with self.assertRaises(ValueError):
            images.hydrate(prepared, 'one', 'deepseek', 'deepseek-flash', self.connection)

    def test_validation_rejects_corruption_oversize_and_too_many_images(self):
        bad = self.root / 'bad.png'
        bad.write_bytes(b'not an image')
        with self.assertRaisesRegex(ValueError, 'invalid_image'):
            files.register('one', bad)
        with patch.object(images, 'MAX_BYTES', 10), self.assertRaisesRegex(ValueError, 'image_limit'):
            files.register('one', self.path)
        for i in range(5):
            path = self.root / f'{i}.png'
            Image.new('RGB', (2, 2)).save(path)
            files.register('one', path)
        path = self.root / 'six.png'
        Image.new('RGB', (2, 2)).save(path)
        with self.assertRaisesRegex(ValueError, 'image_count'):
            files.register('one', path)

    def test_reencoding_applies_orientation_resizes_and_removes_metadata(self):
        path = self.root / 'photo.jpg'
        exif = Image.Exif()
        exif[274] = 6
        exif[270] = 'private metadata'
        Image.new('RGB', (2500, 500), 'green').save(path, exif=exif)
        item = files.register('two', path)
        ai_chat.save_chat('two', [{'role': 'user', 'content': 'image', 'attachments': [item['id']]}])
        url = images.encode('two', item['id'])
        raw = base64.b64decode(url.split(',', 1)[1])
        self.assertNotIn(b'private metadata', raw)
        with Image.open(io.BytesIO(raw)) as image:
            self.assertLess(image.width, image.height)
            self.assertLessEqual(max(image.size), 2048)

    def test_anthropic_image_blocks_and_provider_capabilities(self):
        block = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,YWJj'}}
        _, _, payload = model_providers.request('anthropic', 'claude-sonnet-4-5', self.connection,
                                                [{'role': 'user', 'content': [{'type': 'text', 'text': 'reference'}, block]}], [])
        self.assertEqual('base64', payload['messages'][0]['content'][1]['source']['type'])
        self.assertEqual('YWJj', payload['messages'][0]['content'][1]['source']['data'])
        for provider, model in [('deepseek', 'deepseek-flash'), ('openai', 'gpt-4o'), ('anthropic', 'claude-sonnet-4-5'), ('qwen', 'qwen-vl-max')]:
            self.assertTrue(model_providers.supports_images(provider, model))
        self.assertFalse(model_providers.supports_images('qwen', 'qwen-plus'))
        self.assertTrue(model_providers.supports_images('qwen', 'custom', {'vision_models': ['custom']}))


class ImageAgentTests(ImageFixture, unittest.IsolatedAsyncioTestCase):
    async def test_real_agent_request_has_image_bytes_and_checkpoints_do_not(self):
        captured = []
        def handle(request):
            payload = json.loads(request.content)
            captured.append(payload)
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"The reference contains a red panel."}}]}\n\ndata: [DONE]\n\n')
        original = httpx.AsyncClient
        with patch.object(model_providers, 'active', return_value=('deepseek', 'deepseek-flash', self.connection)), patch.object(agent_model.httpx, 'AsyncClient', side_effect=lambda **kwargs: original(transport=httpx.MockTransport(handle))):
            events = [event async for event in ai_chat.respond(self.messages, chat_id='one')]
        image = captured[0]['messages'][-1]['content'][1]['image_url']['url']
        self.assertTrue(image.startswith('data:image/png;base64,'))
        self.assertTrue(any('red panel' in str(value) for kind, value in events if kind == 'text'))
        self.assertNotIn('base64,', json.dumps(ai_chat.read_chat('one')))
        raw = (self.root / 'agent/checkpoints.sqlite').read_bytes()
        self.assertNotIn(image.encode(), raw)
        self.assertIn(images.PREFIX.encode(), raw)
