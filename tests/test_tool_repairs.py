import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from service.chat import ai_chat
from service.chat import model_providers
from service.tools import tool_repairs


class RepairFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "tools/demo/example.py"
        self.path.parent.mkdir(parents=True)
        self.path.write_text('api_key = "private-tool-key"\ndef main():\n    pass\n')
        for target, value in (("app_dir", self.root), ("tools_dir", self.root / "tools")):
            patcher = patch.object(ai_chat, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(model_providers, "active", return_value=("deepseek", "test", {"key": "provider-key", "base_url": "https://example.test"}))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(model_providers, "load", return_value={"connections": {}})
        patcher.start()
        self.addCleanup(patcher.stop)

    def report(self):
        return tool_repairs.capture(ValueError("secret business body"), "demo", "example")


class RepairTests(RepairFixture, unittest.TestCase):
    def test_summary_does_not_include_raw_error_and_requires_consent(self):
        report_id = self.report()
        report = tool_repairs.get(report_id)
        self.assertNotIn("secret", tool_repairs.summary(report))
        self.assertIsNone(tool_repairs.claim("anything"))
        with self.assertRaises(ValueError):
            tool_repairs.approve(report_id, "wrong-model")
        chat_id = tool_repairs.approve(report_id, tool_repairs.model_fingerprint())
        self.assertEqual(chat_id, tool_repairs.approve(report_id, tool_repairs.model_fingerprint()))
        self.assertEqual(report_id, tool_repairs.claim(chat_id)["id"])
        self.assertIsNone(tool_repairs.claim(chat_id))
        tool_repairs.finish(report_id, False)
        self.assertEqual("failed", tool_repairs.get(report_id)["state"])

    def test_repair_restricts_target_redacts_credentials_and_requires_read(self):
        session = tool_repairs.RepairSession(tool_repairs.get(self.report()))
        args = {"project": "demo", "name": "example"}
        self.assertIn("error", session.execute("read_attachment", args))
        self.assertIn("error", session.execute("read_tool", {**args, "name": "other"}))
        self.assertIn("error", session.execute("preview_tool", {**args, "content": "def main(): pass"}))
        result = session.execute("read_tool", args)
        self.assertNotIn("private-tool-key", result["content"])
        saved = session.execute("write_tool", {**args, **result})
        self.assertTrue(saved["requires_manual_run"])
        self.assertIn("private-tool-key", self.path.read_text())
        self.assertIn("error", session.execute("write_tool", {**args, **result}))

    def test_deleted_chat_cannot_claim_or_reapprove(self):
        report_id = self.report()
        chat_id = tool_repairs.approve(report_id, tool_repairs.model_fingerprint())
        ai_chat.delete_chat(chat_id)
        self.assertIsNone(tool_repairs.claim(chat_id))
        tool_repairs.finish(report_id, False)
        with self.assertRaises(ValueError):
            tool_repairs.approve(report_id, tool_repairs.model_fingerprint())

    def test_concurrent_file_edit_invalidates_revision(self):
        session = tool_repairs.RepairSession(tool_repairs.get(self.report()))
        args = {"project": "demo", "name": "example"}
        result = session.execute("read_tool", args)
        self.path.write_text("def main():\n    return 123\n")
        self.assertIn("error", session.execute("write_tool", {**args, **result}))
        self.assertIn("123", self.path.read_text())

    def test_preview_repair_changes_draft_only(self):
        from service.tools import preview_service
        from service.files import tool_inputs
        draft = self.root / "draft.py"
        draft.write_text("def main(): pass\n")
        chat_id = ai_chat.create_tool_chat("demo", "example", "Example")
        token = tool_inputs.create(chat_id, "preview", [], tool_key="tool:demo/example")
        with patch.object(preview_service, "get_preview_file", return_value=draft):
            report = tool_repairs.get(tool_repairs.capture(RuntimeError(), "demo", "example", preview_key="preview", context=token))
            session = tool_repairs.RepairSession(report)
            args = {"project": "demo", "name": "example"}
            read = session.execute("read_tool", args)
            result = session.execute("write_tool", {**args, "revision": read["revision"], "content": "def main(): return 42\n"})
        self.assertTrue(result["requires_manual_run"])
        self.assertIn("42", draft.read_text())
        self.assertNotIn("42", self.path.read_text())


class RepairModelTests(RepairFixture, unittest.IsolatedAsyncioTestCase):
    async def test_isolated_model_context_and_manual_preview_event(self):
        report_id = self.report()
        chat_id = tool_repairs.approve(report_id, tool_repairs.model_fingerprint())
        report = tool_repairs.claim(chat_id)
        requests = []

        def handle(request):
            payload = json.loads(request.content)
            requests.append(payload)
            count = len(requests)
            args = {"project": "demo", "name": "example"}
            if count == 1:
                name = "read_tool"
            elif count == 2:
                read = json.loads(payload["messages"][-1]["content"])
                name = "write_tool"
                args.update(read)
            else:
                return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"Saved. Retry manually."}}]}\n\ndata: [DONE]\n\n')
            packet = {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": f"call{count}", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}
            return httpx.Response(200, text="data: " + json.dumps(packet) + "\n\ndata: [DONE]\n\n")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        history = [{"role": "user", "content": "OLD PRIVATE ATTACHMENT BODY"}]
        with patch.object(ai_chat.httpx, "AsyncClient", return_value=client):
            events = [event async for event in ai_chat.respond(history, chat_id=chat_id, repair=report)]
        serialized = json.dumps(requests)
        self.assertNotIn("OLD PRIVATE ATTACHMENT BODY", serialized)
        self.assertNotIn("secret business body", serialized)
        self.assertNotIn("private-tool-key", serialized)
        self.assertNotIn("read_attachment", serialized)
        self.assertTrue(any(kind == "manual_preview" for kind, _ in events))
        self.assertFalse(any(kind == "preview" for kind, _ in events))
        self.assertIn("private-tool-key", self.path.read_text())
