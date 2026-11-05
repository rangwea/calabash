import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from core import i18n
from service.chat import ai_chat


class ToolChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        for target, name, value in ((ai_chat, 'app_dir', root),  (i18n, 'app_dir', root)):
            patcher = patch.object(target, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_reuses_conversation_and_preserves_messages_and_user_title(self):
        first = ai_chat.get_or_create_tool_chat('demo', 'one', 'First tool')
        messages = ai_chat.read_chat(first)
        self.assertIn('read_tool', messages[0]['content'])
        self.assertIn('revision', messages[0]['content'])
        messages.append({'role': 'user', 'content': 'Adjust the layout'})
        ai_chat.save_chat(first, messages)
        ai_chat.rename_chat(first, 'My edit conversation')
        again = ai_chat.get_or_create_tool_chat('demo', 'one', 'Updated title')
        self.assertEqual(first, again)
        self.assertEqual(messages, ai_chat.read_chat(again))
        self.assertEqual('My edit conversation', dict(ai_chat.conversations())[again])
        self.assertEqual({'project': 'demo', 'name': 'one', 'title': 'Updated title'}, ai_chat.tool_chat_reference(again))
        other = ai_chat.get_or_create_tool_chat('different', 'one', 'Other project')
        self.assertNotEqual(first, other)

    def test_deleted_chat_is_replaced(self):
        first = ai_chat.get_or_create_tool_chat('demo', 'one', 'First tool')
        with patch('service.chat.agent_store.delete_chat'):
            ai_chat.delete_chat(first)
        self.assertIsNone(ai_chat.tool_chat_reference(first))
        replacement = ai_chat.get_or_create_tool_chat('demo', 'one', 'First tool')
        self.assertNotEqual(first, replacement)
        self.assertEqual(replacement, ai_chat.get_or_create_tool_chat('demo', 'one', 'First tool'))

    def test_concurrent_clicks_create_one_dedicated_conversation(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: ai_chat.get_or_create_tool_chat('demo', 'one', 'First tool'), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(1, len(ai_chat.conversations()))
