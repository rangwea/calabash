import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from service.chat import ai_chat


class AIChatTests(unittest.TestCase):
    def test_first_connection_creates_complete_current_schema(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(ai_chat, "app_dir", return_value=Path(directory)),
        ):
            for _ in range(2):
                with closing(ai_chat.connect()) as db:
                    chats = {row[1] for row in db.execute("PRAGMA table_info(chats)")}
                    self.assertEqual(
                        {
                            "id",
                            "title",
                            "messages",
                            "updated",
                            "pinned",
                            "custom_title",
                            "deleted",
                            "failure",
                        },
                        chats,
                    )
                    self.assertIn(
                        "tool_key",
                        {
                            row[1]
                            for row in db.execute(
                                "PRAGMA table_info(tool_input_contexts)"
                            )
                        },
                    )
                    self.assertIn(
                        "started",
                        {
                            row[1]
                            for row in db.execute("PRAGMA table_info(tool_repairs)")
                        },
                    )
                    self.assertEqual(
                        {
                            "chats",
                            "chat_previews",
                            "tool_chats",
                            "chat_files",
                            "message_files",
                            "tool_input_contexts",
                            "tool_repairs",
                            "output_runs",
                            "output_files",
                        },
                        {
                            row[0]
                            for row in db.execute(
                                "SELECT name FROM sqlite_master WHERE type='table'"
                            )
                        },
                    )

    def test_rename_pin_and_delete_survive_later_saves(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(ai_chat, "app_dir", return_value=Path(directory)),
        ):
            messages = [{"role": "user", "content": "原始标题"}]
            ai_chat.save_chat("one", messages)
            ai_chat.save_chat("two", messages)
            ai_chat.rename_chat("one", "新名称")
            ai_chat.pin_chat("one", True)
            ai_chat.save_chat("one", messages)
            self.assertEqual(("one", "新名称"), ai_chat.conversations()[0])
            self.assertTrue(ai_chat.chat_is_pinned("one"))
            ai_chat.delete_chat("one")
            ai_chat.save_chat("one", messages)
            self.assertEqual([("two", "原始标题")], ai_chat.conversations())
            self.assertEqual([], ai_chat.read_chat("one"))

    def test_write_requires_revision_and_valid_entrypoint(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(ai_chat, "tools_dir", return_value=Path(directory)),
        ):
            args = {
                "project": "demo",
                "name": "hello",
                "content": "def main():\n    pass\n",
            }
            self.assertIn("saved", ai_chat.execute_tool("write_tool", args))
            self.assertIn("error", ai_chat.execute_tool("write_tool", args))
            read = ai_chat.execute_tool("read_tool", args)
            self.assertIn(
                "saved",
                ai_chat.execute_tool(
                    "write_tool", {**args, "revision": read["revision"]}
                ),
            )
            with self.assertRaises(ValueError):
                ai_chat.tool_path("..", "escape")

    def test_conversations_persist(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(ai_chat, "app_dir", return_value=Path(directory)),
        ):
            messages = [{"role": "user", "content": "创建工具"}]
            ai_chat.save_chat("one", messages)
            self.assertEqual(messages, ai_chat.read_chat("one"))
            self.assertEqual([("one", "创建工具")], ai_chat.conversations())
