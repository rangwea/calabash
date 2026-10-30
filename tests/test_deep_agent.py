"""Offline execution tests against the real Deep Agents graph."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

import httpx

from service.chat import agent_model, agent_runtime, agent_store, ai_chat, model_providers


def answer(text="Ready"):
    return {"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}


def call(name, parameters, identity):
    return {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": identity, "function": {
        "name": name, "arguments": json.dumps(parameters),
    }}]}, "finish_reason": "tool_calls"}]}


class DeepAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"HOME": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.requests = []

    def transport(self, script):
        client_class = httpx.AsyncClient

        async def handle(request):
            data = json.loads(request.content)
            self.requests.append(data)
            packet = script(data, len(self.requests))
            if hasattr(packet, "__await__"):
                packet = await packet
            return httpx.Response(200, text="data: " + json.dumps(packet) + "\n\ndata: [DONE]\n\n")

        return patch.object(agent_model.httpx, "AsyncClient", side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handle)))

    def active(self, provider="deepseek", model="deepseek-flash"):
        return patch.object(model_providers, "active", return_value=(provider, model, {"key": "synthetic-only-key", "base_url": "https://example.test"}))

    async def collect(self, messages, chat_id=None, **kwargs):
        return [event async for event in ai_chat.respond(messages, chat_id=chat_id, **kwargs)]

    async def test_incremental_draft_more_than_twelve_rounds_and_no_shell(self):
        source = "def main():\n    pass\n# step-0\n"

        def script(data, n):
            if n == 1:
                return call("write_file", {"file_path": "/drafts/music.py", "content": source}, "create")
            if n <= 14:
                return call("edit_file", {"file_path": "/drafts/music.py", "old_string": f"# step-{n-2}", "new_string": f"# step-{n-1}"}, f"edit-{n}")
            if n == 15:
                return call("deliver_draft", {"project": "demo", "name": "music", "file_path": "/drafts/music.py", "action": "write_tool"}, "save")
            return answer()

        messages = [{"role": "user", "content": "Create music UI"}]
        with self.active(), self.transport(script):
            events = await self.collect(messages, "music-chat")
        self.assertEqual(16, len(self.requests))
        self.assertIn("# step-13", (self.root / ".calabash/tools/demo/music.py").read_text())
        offered = {t["function"]["name"] for t in self.requests[0]["tools"]}
        self.assertNotIn("execute", offered)
        self.assertNotIn("task", offered)
        self.assertIn("write_todos", offered)
        self.assertIn(("text", "Ready"), events)
        self.assertEqual(32768, self.requests[0]["max_tokens"])

    async def test_contract_failure_returns_actionable_diagnosis_to_agent(self):
        def script(data, n):
            if n == 1:
                return call('write_tool', {'project': 'demo', 'name': 'media', 'content': 'from nicegui import ui\ndef main():\n    ui.audio()\n'}, 'invalid')
            if n == 2:
                result = json.loads(data['messages'][-1]['content'])
                self.assertEqual('invalid_component_api', result['diagnosis']['problem'])
                self.assertIn('requires src', str(result['diagnosis']['details']))
                self.assertFalse(result['executed'])
                return call('write_tool', {'project': 'demo', 'name': 'media', 'content': 'def main():\n    pass\n'}, 'corrected')
            return answer()
        with self.active(), self.transport(script):
            await self.collect([{'role': 'user', 'content': 'Create media tool'}])
        self.assertEqual('def main():\n    pass\n', (self.root / '.calabash/tools/demo/media.py').read_text())

    async def test_resume_keeps_completed_write_and_replays_completed_run_without_request(self):
        source = "def main():\n    pass\n"

        def script(data, n):
            if n == 1:
                return call("write_tool", {"project": "demo", "name": "resume", "content": source}, "save-once")
            if n == 2:
                raise httpx.ConnectError("synthetic disconnect")
            return answer()

        messages = [{"role": "user", "content": "Create tool"}]
        with self.active(), self.transport(script), patch.object(ai_chat, "execute_chat_tool", wraps=ai_chat.execute_chat_tool) as execute:
            with self.assertRaises(httpx.ConnectError):
                await self.collect(messages, "resume-chat")
            self.assertTrue(any(m["role"] == "tool" for m in messages))
            # Reload the persisted chat: same behavior after restarting the app.
            messages = ai_chat.read_chat("resume-chat")
            await self.collect(messages, "resume-chat")
            count = len(self.requests)
            await self.collect(messages, "resume-chat")
            self.assertEqual(count, len(self.requests))
            self.assertEqual(1, execute.call_count)
        self.assertEqual(1, sum(m.get("content") == "Ready" for m in messages))

    async def test_budget_pause_resumes_with_new_budget(self):
        def script(data, n):
            if n < 4:
                return call("list_tools", {}, f"list-{n}")
            return answer()

        messages = [{"role": "user", "content": "Several steps"}]
        with self.active(), self.transport(script), patch.object(agent_runtime, "MODEL_CALLS_PER_RUN", 2):
            with self.assertRaises(ValueError):
                await self.collect(messages, "budget-chat")
            await self.collect(messages, "budget-chat")
        self.assertEqual(4, len(self.requests))
        self.assertEqual("Ready", messages[-1]["content"])

    async def test_repeated_calls_pause_but_new_instructions_allow_progress(self):
        def script(data, n):
            return call("list_tools", {}, f"list-{n}") if n <= 4 else answer()

        messages = [{"role": "user", "content": "Create tool"}]
        with self.active(), self.transport(script):
            with self.assertRaises(ValueError):
                await self.collect(messages, "repeated")
            self.assertEqual(4, len(self.requests))
            messages.append({"role": "user", "content": "Stop listing and explain"})
            await self.collect(messages, "repeated")
        self.assertEqual("Ready", messages[-1]["content"])

    async def test_conversations_have_isolated_virtual_files(self):
        async def script(data, n):
            user = next(m["content"] for m in data["messages"] if m["role"] == "user")
            if not any(m["role"] == "tool" for m in data["messages"]):
                await asyncio.sleep(0.01)
                return call("write_file", {"file_path": "/draft.py", "content": user}, user)
            return answer(user)

        first, second = [{"role": "user", "content": "alpha"}], [{"role": "user", "content": "beta"}]
        with self.active(), self.transport(script):
            await asyncio.gather(self.collect(first, "alpha"), self.collect(second, "beta"))
        self.assertEqual("alpha", first[-1]["content"])
        self.assertEqual("beta", second[-1]["content"])
        self.assertNotEqual(first[0]["agent_run_id"], second[0]["agent_run_id"])

    async def test_followup_can_read_its_previous_virtual_draft(self):
        def script(data, n):
            if n == 1:
                return call("write_file", {"file_path": "/draft.py", "content": "original-draft"}, "create")
            if n == 3:
                return call("read_file", {"file_path": "/draft.py"}, "read-again")
            return answer()

        messages = [{"role": "user", "content": "Create draft"}]
        with self.active(), self.transport(script):
            await self.collect(messages, "followup")
            messages.append({"role": "user", "content": "Continue editing"})
            await self.collect(messages, "followup")
        result = next(m for m in messages if m.get("tool_call_id") == "read-again")
        self.assertIn("original-draft", result["content"])
        self.assertNotIn("not found", result["content"].lower())

    async def test_large_source_triggers_internal_summary_without_exposing_it_as_answer(self):
        source = "def main():\n    pass\n" + "# synthetic source\n" * 5000

        def script(data, n):
            if n == 1:
                return call("write_file", {"file_path": "/large.py", "content": source}, "large-draft")
            if n == 2:
                return answer("Internal summary: /large.py is a virtual draft. Finish the reply.")
            return answer()

        messages = [{"role": "user", "content": "Create large draft"}]
        with self.active(), self.transport(script):
            events = await self.collect(messages, "large")
        self.assertEqual(3, len(self.requests))
        self.assertNotIn(("text", "Internal summary: /large.py is a virtual draft. Finish the reply."), events)
        self.assertEqual("Ready", messages[-1]["content"])

    async def test_cancel_preserves_progress_and_allows_resume(self):
        waiting = asyncio.Event()

        async def script(data, n):
            if n == 1:
                return call("write_file", {"file_path": "/draft.py", "content": "retained"}, "write-once")
            if n == 2:
                waiting.set()
                await asyncio.Future()
            return answer()

        messages = [{"role": "user", "content": "Create draft"}]
        with self.active(), self.transport(script):
            task = asyncio.create_task(self.collect(messages, "cancel"))
            await asyncio.wait_for(waiting.wait(), 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(messages[0]["agent_completed"])
            await self.collect(messages, "cancel")
            self.assertTrue(messages[0]["agent_completed"])
        self.assertEqual(3, len(self.requests))
        self.assertEqual(1, sum(m.get("tool_call_id") == "write-once" for m in messages))

    async def test_truncation_retry_requests_small_incremental_edits(self):
        def script(data, n):
            if n == 1:
                return {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "incomplete", "function": {"name": "write_tool", "arguments": '{"content":"unfinished'}}]}, "finish_reason": "length"}]}
            return answer()

        messages = [{"role": "user", "content": "Create long tool"}]
        with self.active(), self.transport(script), patch.object(ai_chat, "execute_chat_tool") as execute:
            with self.assertRaises(agent_model.OutputLimitError):
                await self.collect(messages, "truncated")
            await self.collect(messages, "truncated")
            execute.assert_not_called()
        self.assertIn("Previous response was truncated", self.requests[-1]["messages"][0]["content"])

    async def test_repair_target_guard_and_regular_tools_preserved(self):
        from service.tools.tool_repairs import model_fingerprint
        target = self.root / ".calabash/tools/demo/music.py"
        target.parent.mkdir(parents=True)
        target.write_text("def main():\n    pass\n")

        def script(data, n):
            if n == 1:
                return call("stage_tool", {"project": "demo", "name": "music"}, "read")
            if n == 2:
                return call("write_tool", {"project": "other", "name": "blocked", "content": "def main():\n    pass\n"}, "blocked")
            if n == 3:
                return call("edit_file", {"file_path": "/drafts/demo/music.py", "old_string": "pass", "new_string": "return 42"}, "edit")
            if n == 4:
                revision = json.loads(next(m["content"] for m in data["messages"] if m.get("tool_call_id") == "read"))["revision"]
                return call("deliver_draft", {"project": "demo", "name": "music", "file_path": "/drafts/demo/music.py", "revision": revision, "action": "write_tool"}, "save")
            return answer("Please retry manually")

        messages = [{"role": "user", "content": "Repair"}]
        with self.active(), self.transport(script), patch("service.tools.preview_service.get_preview_file", return_value=target):
            report = {"project": "demo", "name": "music", "preview_key": "synthetic", "context": "synthetic", "phase": "render", "exception": "ValueError", "lines": [], "model_fingerprint": model_fingerprint()}
            events = await self.collect(messages, repair=report)
        self.assertIn("return 42", target.read_text())
        self.assertFalse((self.root / ".calabash/tools/other/blocked.py").exists())
        self.assertTrue(any(kind == "manual_preview" for kind, _ in events))
        offered = {t["function"]["name"] for t in self.requests[0]["tools"]}
        self.assertIn("read_attachment", offered)
        self.assertIn("read_ui_reference", offered)
        self.assertNotIn("execute", offered)

    async def test_operation_receipts_do_not_repeat_unknown_side_effect(self):
        self.assertIsNone(agent_store.begin("run", "call", "arguments"))
        self.assertIn("error", agent_store.begin("run", "call", "arguments"))
        agent_store.finish("run", "call", {"saved": True})
        self.assertEqual({"saved": True}, agent_store.begin("run", "call", "arguments"))
        self.assertIn("error", agent_store.begin("run", "call", "changed"))

    async def test_delete_cleans_execution_state(self):
        messages = [{"role": "user", "content": "Hi"}]
        with self.active(), self.transport(lambda data, n: answer()):
            await self.collect(messages, "deleted")
        ai_chat.delete_chat("deleted")
        self.assertFalse(ai_chat.chat_exists("deleted"))
        with closing(agent_store.connect()) as db:
            self.assertEqual([], db.execute("SELECT id FROM runs WHERE chat_id='deleted'").fetchall())

    async def test_no_credentials_in_model_serialization_or_run_config(self):
        model = agent_model.CalabashChatModel("deepseek", "deepseek-flash", {"key": "secret-not-metadata", "base_url": "https://example.test"})
        self.assertNotIn("secret-not-metadata", str(model.to_json()))
        self.assertNotIn("secret-not-metadata", repr(model))


if __name__ == "__main__":
    unittest.main()
