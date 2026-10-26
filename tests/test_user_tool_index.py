import unittest
from unittest.mock import patch

from nicegui import ui

from ui import sidebar as index
from ui.tool_list import _tool_display_name, use_tool


class UserToolIndexTest(unittest.TestCase):
    def test_recent_conversations_are_above_recent_tools(self):
        for chats in ([], [("chat-one", "Example conversation")]):
            with self.subTest(chats=chats):
                container = ui.column()
                try:
                    with (
                        container,
                        patch.object(index, "t", side_effect=lambda text: text),
                        patch.object(index, "_get_recent_tools", return_value=[]),
                        patch("service.chat.ai_chat.conversations", return_value=chats),
                        patch("service.chat.ai_chat.chat_is_pinned", return_value=False),
                    ):
                        index._render_desktop_sidebar(
                            [], "tools", lambda _: None, lambda *_: None
                        )
                    labels = [
                        element.text
                        for element in container.descendants()
                        if isinstance(element, ui.label)
                    ]
                    self.assertLess(labels.index("最近对话"), labels.index("最近工具"))
                finally:
                    container.delete()

    def test_display_name_prefers_metadata_title(self):
        tool = {"name": "http_requester", "title": "HTTP 请求工具"}

        self.assertEqual(_tool_display_name(tool), "HTTP 请求工具")

    @patch("ui.tool_list.ui.navigate.to")
    def test_use_tool_navigates_with_filename_identifier(self, navigate):
        tool = {
            "project": "toolkit",
            "name": "http-requester",
            "title": "HTTP 请求工具",
        }

        use_tool(tool)

        navigate.assert_called_once_with("/tools/toolkit/http-requester")


if __name__ == "__main__":
    unittest.main()
