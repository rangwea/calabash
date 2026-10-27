import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nicegui import core, ui

from component.ai_chat import render_ai_chat
from core import i18n
from service.chat import ai_chat
from service.chat import model_providers


class ChatResponseUITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.container = ui.column()

    async def test_two_conversations_run_independently_and_keep_drafts(self):
        started = {key: asyncio.Event() for key in ("one", "two")}
        released = {key: asyncio.Event() for key in started}
        changes = []

        async def respond(messages, chat_id=None):
            started[chat_id].set()
            yield "activity", "thinking"
            await released[chat_id].wait()
            messages.append({"role": "assistant", "content": f"Finished {chat_id}"})
            yield "text", f"Finished {chat_id}"

        async def settle():
            for _ in range(12):
                await asyncio.sleep(0)

        def pane(chat_id):
            return next(item for item in self.container.descendants() if item._props.get("data-chat-session") == chat_id)

        def composer(chat_id):
            return next(item for item in pane(chat_id).descendants() if isinstance(item, ui.textarea))

        def send(chat_id):
            button = next(item for item in pane(chat_id).descendants() if "chat-send" in item._classes)
            with pane(chat_id):
                next(iter(button._event_listeners.values())).handler(None)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(core, "loop", asyncio.get_running_loop()), patch.object(ai_chat, "app_dir", return_value=root), patch.object(i18n, "app_dir", return_value=root), patch.object(model_providers, "selected", return_value="test::model"), patch.object(model_providers, "options", return_value={"test::model": "Test"}), patch.object(ai_chat, "respond", respond):
                with self.container:
                    switch = render_ai_chat("one", on_change=changes.append)
                composer("one").set_value("First request")
                send("one")
                await settle()
                switch("two")
                composer("two").set_value("Second request")
                send("two")
                await settle()
                self.assertTrue(all(event.is_set() for event in started.values()))
                self.assertFalse(pane("one").visible)
                self.assertTrue(pane("two").visible)
                composer("two").set_value("Unsent draft")
                released["one"].set()
                await settle()
                self.assertEqual(changes[-1], "two")
                self.assertEqual(ai_chat.read_chat("one")[-1]["content"], "Finished one")
                self.assertFalse(any(m.get("content") == "Finished one" for m in ai_chat.read_chat("two")))
                switch("one")
                switch("two")
                self.assertEqual(composer("two").value, "Unsent draft")
                stop = next(item for item in pane("two").descendants() if isinstance(item, ui.button) and item.icon == "stop")
                with pane("two"):
                    next(iter(stop._event_listeners.values())).handler(None)
                await settle()
                self.assertEqual(ai_chat.read_chat("one")[-1]["content"], "Finished one")
                self.assertEqual(ai_chat.read_chat("two")[-1]["content"], "Second request")

    async def test_repaired_preview_is_not_restored_automatically(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(core, "loop", asyncio.get_running_loop()), patch.object(ai_chat, "app_dir", return_value=root), patch.object(model_providers, "options", return_value={}):
                ai_chat.save_chat("repair", [
                    {"role": "tool", "content": json.dumps({"success": True, "preview_url": "/preview/old"})},
                    {"role": "tool", "repair_completed": True, "content": json.dumps({"success": True, "requires_manual_run": True, "preview_url": "/preview/repaired", "url": "/preview/repaired"})},
                ])
                with self.container:
                    render_ai_chat("repair")
                self.assertFalse(any(element.tag == "iframe" for element in self.container.descendants()))
                self.assertTrue(any("chat-repair-retry" in element._classes for element in self.container.descendants()))

    def test_repair_handoff_passes_opaque_id_to_home(self):
        from fastapi import Request

        from ui.pages import home as index

        request = Request({"type": "http", "query_string": b"repair=opaque-id"})
        with patch.object(index, "render_desktop_home") as render:
            index.home_page(request)
        render.assert_called_once_with(repair_id="opaque-id")

    async def test_incomplete_saved_repair_does_not_offer_retry_on_reload(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(core, "loop", asyncio.get_running_loop()), patch.object(ai_chat, "app_dir", return_value=root), patch.object(model_providers, "options", return_value={}):
                ai_chat.save_chat("repair", [{"role": "tool", "content": json.dumps({"success": True, "requires_manual_run": True, "preview_url": "/preview/incomplete", "url": "/preview/incomplete"})}])
                with self.container:
                    render_ai_chat("repair")
                self.assertFalse(any("chat-repair-retry" in element._classes for element in self.container.descendants()))
                self.assertFalse(any(element.tag == "iframe" for element in self.container.descendants()))

    async def test_completed_repair_shows_only_one_manual_retry_button(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = {"success": True, "requires_manual_run": True, "preview_url": "/preview/repaired", "url": "/preview/repaired"}
            saved = asyncio.Event()
            finish = asyncio.Event()

            async def respond(messages, chat_id=None):
                messages.append({"role": "tool", "content": json.dumps(result)})
                yield "manual_preview", result
                saved.set()
                await finish.wait()
                messages.append({"role": "assistant", "content": "Saved"})
                yield "text", "Saved"

            with patch.object(core, "loop", asyncio.get_running_loop()), patch.object(ai_chat, "app_dir", return_value=root), patch.object(i18n, "app_dir", return_value=root), patch.object(model_providers, "selected", return_value="test::model"), patch.object(model_providers, "options", return_value={"test::model": "Test"}), patch.object(ai_chat, "respond", respond):
                with self.container:
                    switch = render_ai_chat("repair")
                composer = next(element for element in self.container.descendants() if isinstance(element, ui.textarea))
                send = next(element for element in self.container.descendants() if "chat-send" in element._classes)
                composer.set_value("Repair the tool")
                with self.container:
                    next(iter(send._event_listeners.values())).handler(None)
                for _ in range(10):
                    await asyncio.sleep(0)
                self.assertTrue(saved.is_set())
                self.assertFalse(any("chat-repair-retry" in element._classes for element in self.container.descendants()))
                finish.set()
                for _ in range(10):
                    await asyncio.sleep(0)
                for reload_chat in (False, True):
                    if reload_chat:
                        with self.container:
                            switch("repair")
                        for _ in range(5):
                            await asyncio.sleep(0)
                    buttons = [element for element in self.container.descendants() if isinstance(element, ui.button) and element.text == i18n.t("修复已保存，手动重试运行")]
                    self.assertEqual(1, len(buttons))
                    self.assertEqual("o_restart_alt", buttons[0]._props["icon"])
                    self.assertIn("chat-repair-retry", buttons[0]._classes)
                    self.assertFalse(any(element.tag == "iframe" for element in self.container.descendants()))

    async def test_background_error_is_visible_and_retry_does_not_duplicate_message(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []

            async def respond(messages, chat_id=None):
                calls.append(True)
                if len(calls) == 1:
                    raise ValueError("test rejected request")
                messages.append({"role": "assistant", "content": "success"})
                yield "text", "success"

            with patch.object(core, "loop", asyncio.get_running_loop()), patch.object(ai_chat, "app_dir", return_value=root), patch.object(i18n, "app_dir", return_value=root), patch.object(model_providers, "selected", return_value="test::model"), patch.object(model_providers, "options", return_value={"test::model": "Test"}), patch.object(ai_chat, "respond", respond), patch.object(ui, "notify", wraps=ui.notify) as notify:
                container = self.container
                with container:
                    render_ai_chat("test")
                elements = list(container.descendants())
                composer = next(element for element in elements if isinstance(element, ui.textarea))
                send = next(element for element in elements if "chat-send" in element._classes)
                composer.set_value("hello")
                with container:
                    next(iter(send._event_listeners.values())).handler(None)
                for _ in range(10):
                    await asyncio.sleep(0)
                self.assertTrue(send.enabled)
                notify.assert_called_with("test rejected request", type="negative")
                retry = next(element for element in container.descendants() if isinstance(element, ui.button) and element._props.get("icon") == "refresh")
                with container:
                    next(iter(retry._event_listeners.values())).handler(None)
                for _ in range(10):
                    await asyncio.sleep(0)
                saved = ai_chat.read_chat("test")
                self.assertEqual(1, sum(message["role"] == "user" for message in saved))
                self.assertEqual("success", saved[-1]["content"])
                self.assertTrue(send.enabled)
