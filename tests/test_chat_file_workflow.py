import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from nicegui import ui

from service.chat import ai_chat, agent_model
from service.chat import chat_context
from service.files import conversation_files
from service.chat import model_providers
from service.files import tool_inputs


class ChatFileWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for module, attribute in [(ai_chat, "app_dir"), (ai_chat, "tools_dir")]:
            patcher = patch.object(module, attribute, return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        path = self.root / "office.csv"
        path.write_text("team,person,amount\nA,Alice,10\nB,Bob,20\n")
        self.item = conversation_files.register("one", path)
        self.messages = [{"role": "user", "content": "Build a chart", "attachments": [self.item["id"]]}]
        ai_chat.save_chat("one", self.messages)

    async def test_mock_model_reads_file_then_builds_context_bound_preview(self):
        requests = []
        code = "def main():\n    from component.tool_files import ToolFileInput\n    inputs = ToolFileInput()\n"
        steps = [("list_attachments", {}), ("read_attachment", {"file_id": self.item["id"], "limit": 1}),
                 ("write_tool", {"project": "demo", "name": "chart", "content": code}),
                 ("preview_tool", {"project": "demo", "name": "chart", "content": code})]

        def handle(request):
            payload = json.loads(request.content)
            requests.append(payload)
            if len(requests) <= len(steps):
                name, arguments = steps[len(requests) - 1]
                delta = {"tool_calls": [{"index": 0, "id": f"call-{len(requests)}", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
            else:
                delta = {"content": "Ready"}
            data = "data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\ndata: [DONE]\n\n"
            return httpx.Response(200, text=data, headers={"content-type": "text/event-stream"})

        client_class = httpx.AsyncClient
        from service.tools import preview_service
        preview_result = {"success": True, "key": "preview-key", "preview_url": "/preview/preview-key"}
        with patch.object(model_providers, "active", return_value=("deepseek", "model", {"key": "secret", "base_url": "https://example.test"})), patch.object(agent_model.httpx, "AsyncClient", side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handle))), patch.object(preview_service, "create_fixed_preview", return_value=preview_result):
            events = [event async for event in ai_chat.respond(self.messages, chat_id="one")]
        self.assertEqual(5, len(requests))
        from core.runtime_capabilities import agent_guidance
        self.assertIn(agent_guidance(), requests[0]["messages"][0]["content"])
        self.assertNotIn("Alice", json.dumps(requests[0]))
        self.assertIn("Alice", json.dumps(requests[2]))
        self.assertNotIn(str(self.root), json.dumps(requests[:3]))
        preview = next(value for kind, value in events if kind == "preview")
        token = preview["preview_url"].split("context=", 1)[1]
        self.assertEqual(self.item["id"], tool_inputs.resolve(token, "preview-key")[0]["id"])
        with self.assertRaises(ValueError):
            tool_inputs.resolve(token, "other-preview")
        ai_chat.delete_chat("one")
        with self.assertRaises(ValueError):
            tool_inputs.resolve(token, "preview-key")

    async def test_file_tools_reject_arbitrary_paths_and_cross_chat(self):
        result = await ai_chat.execute_chat_tool("read_attachment", {"file_id": self.item["id"], "path": str(self.root / "office.csv")}, "one")
        self.assertEqual("invalid_options", result["error"]["code"])
        result = await ai_chat.execute_chat_tool("read_attachment", {"file_id": self.item["id"]}, "two")
        self.assertEqual("not_found", result["error"]["code"])

    def test_context_compaction_preserves_complete_tool_pairs(self):
        messages = [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "tool_calls": [{"id": "call", "function": {"name": "read_tool", "arguments": "x" * 2000}}]},
            {"role": "tool", "tool_call_id": "call", "content": "old result"},
            {"role": "user", "content": "new"},
        ]
        with patch.object(chat_context, "MAX_HISTORY_CHARACTERS", 200):
            prepared = chat_context.prepare(messages)
        self.assertEqual("new", prepared[-1]["content"])
        self.assertFalse(any(message["role"] == "tool" for message in prepared))
        self.assertEqual("instructions", prepared[0]["content"])
        self.assertEqual(5, len(messages))

    def test_failures_restore_but_do_not_revive_deleted_chats(self):
        ai_chat.save_failure("one", "request rejected")
        self.assertEqual("request rejected", ai_chat.read_failure("one"))
        ai_chat.delete_chat("one")
        ai_chat.save_failure("one", "late failure")
        self.assertEqual("", ai_chat.read_failure("one"))

    async def test_model_validation_rejects_unknown_id_without_saving(self):
        async def available(*args):
            return ["valid-model"]
        with patch.object(model_providers, "available_models", available):
            with self.assertRaises(ValueError):
                await model_providers.validate_connection("deepseek", {"models": ["deepseek"]})
            self.assertEqual(["valid-model"], await model_providers.validate_connection("deepseek", {"models": ["valid-model"]}))

    async def test_model_validation_uses_only_get_models(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"data": [{"id": "valid-model"}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch.object(model_providers.httpx, "AsyncClient", return_value=client):
            result = await model_providers.validate_connection("deepseek", {"base_url": "https://example.test", "key": "secret", "models": ["valid-model"]})
        self.assertEqual(["valid-model"], result)
        self.assertEqual("GET", requests[0].method)
        self.assertEqual("/models", requests[0].url.path)
        self.assertEqual(b"", requests[0].content)

    def test_shared_tool_input_checks_changed_files_and_expired_context(self):

        from component.tool_files import ToolFileInput
        token = tool_inputs.create("one", "preview", self.messages)
        with patch.object(ui.context.client, "calabash_input_context", (token, "preview"), create=True):
            selector = ToolFileInput()
            self.assertEqual(str((self.root / "office.csv").resolve()), selector.paths[0])
            (self.root / "office.csv").write_text("changed")
            with self.assertRaises(ValueError):
                _ = selector.paths
            ai_chat.delete_chat("one")
            with self.assertRaises(ValueError):
                _ = selector.paths
