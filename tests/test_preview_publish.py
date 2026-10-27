import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.chat import ai_chat
from service.files import tool_inputs
from service.tools import preview_publish, preview_service, tool_activity


class PreviewPublishTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for module, name, value in (
            (ai_chat, 'app_dir', self.root),
            (ai_chat, 'tools_dir', self.root / 'tools'),
        ):
            patcher = patch.object(module, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.draft = self.root / 'preview.py'
        self.draft.write_text('def main():\n    return 42\n')
        patcher = patch.object(preview_service, 'get_preview_file', return_value=self.draft)
        patcher.start()
        self.addCleanup(patcher.stop)
        ai_chat.save_chat('chat', [{'role': 'user', 'content': 'synthetic'}])
        self.token = tool_inputs.create('chat', 'draft', [], tool_key='tool:demo/example')
        self.url = f'/preview/draft?context={self.token}'
        self.target = self.root / 'tools/demo/example.py'

    def test_create_is_exact_source_without_running(self):
        self.draft.write_text('raise RuntimeError("must not execute")\ndef main(): pass\n')
        snapshot = preview_publish.prepare('chat', self.url)
        preview_publish.save(snapshot)
        self.assertEqual(self.draft.read_bytes(), self.target.read_bytes())

    def test_overwrite_requires_confirmation_and_preserves_cancelled_target(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text('def main(): return 1\n')
        snapshot = preview_publish.prepare('chat', self.url)
        with self.assertRaises(ValueError):
            preview_publish.save(snapshot)
        self.assertIn('return 1', self.target.read_text())
        preview_publish.save(snapshot, overwrite=True)
        self.assertEqual(self.draft.read_bytes(), self.target.read_bytes())

    def test_confirmation_invalidated_by_source_or_target_changes(self):
        snapshot = preview_publish.prepare('chat', self.url)
        self.draft.write_text('def main(): return 99\n')
        with self.assertRaises(ValueError):
            preview_publish.save(snapshot, overwrite=True)
        snapshot = preview_publish.prepare('chat', self.url)
        self.target.parent.mkdir(parents=True)
        self.target.write_text('def main(): return 1\n')
        with self.assertRaises(ValueError):
            preview_publish.save(snapshot, overwrite=True)
        self.assertIn('return 1', self.target.read_text())

    def test_running_tool_is_blocked_even_after_confirmation(self):
        snapshot = preview_publish.prepare('chat', self.url)
        with patch.object(tool_activity, 'is_tool_running', return_value=True):
            with self.assertRaises(tool_activity.ToolBusyError):
                preview_publish.save(snapshot, overwrite=True)
        self.assertFalse(self.target.exists())

    def test_context_binding_expiry_and_routes_are_checked(self):
        for chat_id, url in [('other', self.url), ('chat', '/preview/other?context=' + self.token),
                             ('chat', 'https://example.test' + self.url), ('chat', '/preview/draft')]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                preview_publish.prepare(chat_id, url)
        ai_chat.delete_chat('chat')
        with self.assertRaises(ValueError):
            preview_publish.prepare('chat', self.url)

    def test_fixed_route_and_invalid_code(self):
        key = preview_service.fixed_preview_key_from_path('ai', 'demo-example')
        token = tool_inputs.create('chat', key, [], tool_key='tool:demo/example')
        snapshot = preview_publish.prepare('chat', f'/preview/ai/demo-example?context={token}')
        self.assertEqual('example', snapshot.name)
        self.draft.write_text('print("no main")')
        with self.assertRaises(ValueError):
            preview_publish.prepare('chat', self.url)
