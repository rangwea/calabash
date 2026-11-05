"""Offline execution tests against the real Deep Agents graph."""

import asyncio
import json
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import httpx

from service.chat import (
    agent_model,
    agent_runtime,
    agent_store,
    ai_chat,
    model_providers,
)


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

    async def test_large_completed_source_avoids_extra_summary_model_call(self):
        source = "def main():\n    pass\n" + "# synthetic source\n" * 5000

        def script(data, n):
            if n == 1:
                return call("write_file", {"file_path": "/large.py", "content": source}, "large-draft")
            self.assertLess(len(json.dumps(data["messages"])), 40000)
            self.assertNotIn(source, json.dumps(data["messages"]))
            return answer()

        messages = [{"role": "user", "content": "Create large draft"}]
        with self.active(), self.transport(script):
            events = await self.collect(messages, "large")
        self.assertEqual(2, len(self.requests))
        self.assertIn(("text", "Ready"), events)
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
