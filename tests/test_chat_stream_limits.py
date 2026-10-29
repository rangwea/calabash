import asyncio
import json
import unittest
import tempfile
import os
from unittest.mock import patch

import httpx

from service.chat import ai_chat, agent_model, model_providers


class SlowStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        while True:
            yield b": heartbeat\n\n"
            await asyncio.sleep(0.01)


class ChatStreamLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.env = patch.dict(os.environ, {"HOME": self.home.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def collect(self, packets=None, stream=None):
        def handle(request):
            self.payload = json.loads(request.content)
            if stream:
                return httpx.Response(200, stream=stream)
            data = "".join("data: " + json.dumps(packet) + "\n\n" for packet in packets)
            return httpx.Response(200, text=data + "data: [DONE]\n\n")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with (
            patch.object(model_providers, "active", return_value=("deepseek", "deepseek-flash", {"key": "synthetic", "base_url": "https://example.test"})),
            patch.object(agent_model.httpx, "AsyncClient", return_value=client),
        ):
            return [event async for event in ai_chat.respond([{"role": "user", "content": "Create a tool"}])]

    async def test_reasoning_only_response_does_not_silently_finish(self):
        with self.assertRaises(ValueError):
            await self.collect([{"choices": [{"delta": {"reasoning_content": "hidden"}}]}])
        self.assertEqual({"type": "disabled"}, self.payload["thinking"])

    async def test_heartbeats_cannot_keep_request_open_forever(self):
        with patch.object(ai_chat, "MODEL_REQUEST_TIMEOUT", 0.025):
            with self.assertRaises(TimeoutError):
                await self.collect(stream=SlowStream())

    async def test_truncated_tool_call_is_not_executed(self):
        packets = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "one", "function": {"name": "write_tool", "arguments": '{"content":"partial'}}]}, "finish_reason": "length"}]}]
        with patch.object(ai_chat, "execute_chat_tool") as execute:
            with self.assertRaises(ValueError):
                await self.collect(packets)
            execute.assert_not_called()

    async def test_anthropic_max_tokens_followed_by_message_stop_still_rejects_call(self):
        packets = [
            {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "one", "name": "write_tool"}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "{}"}},
            {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
            {"type": "message_stop"},
        ]
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="".join("data: " + json.dumps(p) + "\n\n" for p in packets))))
        with patch.object(model_providers, "active", return_value=("anthropic", "synthetic", {"key": "synthetic", "base_url": "https://example.test"})), patch.object(agent_model.httpx, "AsyncClient", return_value=client), patch.object(ai_chat, "execute_chat_tool") as execute:
            with self.assertRaises(agent_model.OutputLimitError):
                _ = [event async for event in ai_chat.respond([{"role": "user", "content": "Create tool"}])]
            execute.assert_not_called()

    async def test_anthropic_stream_completes_with_existing_protocol(self):
        packets = [
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Ready"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {"type": "message_stop"},
        ]
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="".join("data: " + json.dumps(p) + "\n\n" for p in packets))))
        with patch.object(model_providers, "active", return_value=("anthropic", "synthetic", {"key": "synthetic", "base_url": "https://example.test"})), patch.object(agent_model.httpx, "AsyncClient", return_value=client):
            events = [event async for event in ai_chat.respond([{"role": "user", "content": "Hello"}])]
        self.assertIn(("text", "Ready"), events)

    async def test_tool_generation_status_precedes_execution(self):
        packets = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "one", "function": {"name": "list_tools", "arguments": "{}"}}]}}]}]
        final = {"choices": [{"delta": {"content": "Ready"}}]}
        count = 0

        def handle(request):
            nonlocal count
            count += 1
            value = packets[0] if count == 1 else final
            return httpx.Response(200, text="data: " + json.dumps(value) + "\n\ndata: [DONE]\n\n")

        client_class = httpx.AsyncClient
        with patch.object(model_providers, "active", return_value=("deepseek", "model", {"key": "synthetic", "base_url": "https://example.test"})), patch.object(agent_model.httpx, "AsyncClient", side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handle))), patch.object(ai_chat, "execute_chat_tool", return_value=[]):
            events = [event async for event in ai_chat.respond([{"role": "user", "content": "List tools"}])]
        self.assertLess(events.index(("activity", "generating_tool")), events.index(("activity", "list_tools")))
