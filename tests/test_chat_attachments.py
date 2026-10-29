import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from nicegui import ui
from nicegui.elements.upload_files import SmallFileUpload

from component import chat_attachments
from service.chat import ai_chat
from service.files import conversation_files


class ChatAttachmentsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        patcher = patch.object(ai_chat, "app_dir", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.selected = "one"
        self.changed = Mock()
        self.container = ui.column()
        self.controls = chat_attachments.ChatAttachments(lambda: self.selected, self.changed)
        self.controls.render.refresh = Mock()

    async def test_native_picker_remembers_original_conversation(self):
        async def choose():
            self.selected = "two"
            return {"ticket": "ticket"}

        with patch.object(chat_attachments, "choose_chat_files", choose), patch.object(conversation_files, "consume_selection", return_value=[]) as consume:
            await self.controls.select()
        consume.assert_called_once_with("one", "ticket")
        self.changed.assert_called_once_with("one")

    async def test_native_cancel_does_not_open_upload_or_change_drafts(self):
        with patch.object(chat_attachments, "choose_chat_files", AsyncMock(return_value={"ticket": None})), patch.object(self.controls, "upload_dialog") as dialog:
            await self.controls.select()
        dialog.assert_not_called()
        self.changed.assert_not_called()

    def test_drop_permission_failure_does_not_block_following_selection(self):
        denied, ready = "a" * 32, "b" * 32
        with patch.object(conversation_files, "consume_selection", side_effect=[PermissionError("denied"), []]) as consume, patch.object(ui, "notify") as notify:
            self.controls.consume("one", denied)
            self.controls.consume("one", ready)
        self.assertEqual(2, consume.call_count)
        self.assertEqual(chat_attachments.t("无法添加文件，请检查文件是否存在及访问权限"), notify.call_args.args[0])
        self.changed.assert_called_once_with("one")
        self.assertFalse(self.controls.busy)

    async def test_native_command_failure_is_not_reported_as_file_access_error(self):
        result = {"error": "picker_failed", "detail": "select_chat_files not allowed"}
        with patch.object(chat_attachments, "choose_chat_files", AsyncMock(return_value=result)), patch.object(ui, "notify") as notify:
            await self.controls.select()
        self.assertEqual(chat_attachments.t("无法打开系统选择器，请重启应用后重试"), notify.call_args.args[0])

    def test_native_command_permissions_cover_the_localhost_page(self):
        import json
        root = Path(__file__).resolve().parents[1] / "src-tauri"
        capability = json.loads((root / "capabilities/local-frame.json").read_text())
        self.assertIn("http://127.0.0.1:*", capability["remote"]["urls"])
        self.assertIn("allow-select-chat-files", capability["permissions"])
        self.assertIn('"select_chat_files"', (root / "build.rs").read_text())

    async def test_browser_fallback_and_upload_binds_original_chat(self):
        with self.container, patch.object(chat_attachments, "choose_chat_files", AsyncMock(return_value={"browser": True})):
            await self.controls.select()
        uploader = next(element for element in reversed(list(self.container.client.elements.values())) if isinstance(element, ui.upload))
        self.selected = "two"
        uploader._begin_upload_handlers[0]()
        self.assertTrue(self.controls.busy)
        await uploader._multi_upload_handlers[0](SimpleNamespace(files=[SmallFileUpload("office.txt", "text/plain", b"office")]))
        self.assertFalse(self.controls.busy)
        self.assertEqual("office.txt", conversation_files.list_files("one", pending=True)[0]["name"])
        self.assertEqual([], conversation_files.list_files("two", pending=True))

    async def test_upload_failure_always_clears_busy(self):
        with self.container:
            self.controls.upload_dialog("one")
        uploader = next(element for element in reversed(list(self.container.client.elements.values())) if isinstance(element, ui.upload))
        uploader._begin_upload_handlers[0]()
        with patch.object(conversation_files, "store_upload", AsyncMock(side_effect=ValueError("limit"))), patch.object(ui, "notify"):
            await uploader._multi_upload_handlers[0](SimpleNamespace(files=[SmallFileUpload("office.txt", "text/plain", b"office")]))
        self.assertFalse(self.controls.busy)

    async def test_pasted_images_upload_to_original_chat_and_render_thumbnail(self):
        import io
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', (16, 12), 'red').save(buffer, format='PNG')
        with self.container:
            compose = chat_attachments.NativeFileDrop()
            self.controls.connect_drop(compose)
        uploader = next(element for element in reversed(list(self.container.client.elements.values())) if isinstance(element, ui.upload))
        self.assertEqual(uploader._props['url'], compose._props['imageUploadUrl'])
        self.selected = 'two'
        uploader._begin_upload_handlers[0]()
        with self.container, patch.object(compose, 'run_method') as done:
            await uploader._multi_upload_handlers[0](SimpleNamespace(files=[SmallFileUpload('pasted.png', 'image/png', buffer.getvalue())]))
        self.assertFalse(self.controls.busy)
        done.assert_called_once_with('uploadDone')
        item = conversation_files.list_files('one', pending=True)[0]
        self.assertEqual('pasted.png', item['name'])
        self.assertEqual([], conversation_files.list_files('two', pending=True))
        with self.container:
            chat_attachments.render_file(item, 'one')
        thumbnails = [element for element in self.container.client.elements.values() if isinstance(element, ui.image)]
        self.assertTrue(any(element._props['src'].startswith('data:image/png;base64,') for element in thumbnails))
