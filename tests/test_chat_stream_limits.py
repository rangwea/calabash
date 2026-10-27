import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from service.chat import ai_chat, model_providers


class SlowStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        while True:
            yield b": heartbeat\n\n"
            await asyncio.sleep(0.01)


class ChatStreamLimitTests(unittest.IsolatedAsyncioTestCase):
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
            patch.object(ai_chat.httpx, "AsyncClient", return_value=client),
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

    async def test_tool_generation_status_precedes_execution(self):
        packets = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "one", "function": {"name": "list_tools", "arguments": "{}"}}]}}]}]
        final = {"choices": [{"delta": {"content": "Ready"}}]}
        count = 0

        def handle(request):
            nonlocal count
            count += 1
            value = packets[0] if count == 1 else final
            return httpx.Response(200, text="data: " + json.dumps(value) + "\n\ndata: [DONE]\n\n")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch.object(model_providers, "active", return_value=("deepseek", "model", {"key": "synthetic", "base_url": "https://example.test"})), patch.object(ai_chat.httpx, "AsyncClient", return_value=client), patch.object(ai_chat, "execute_chat_tool", return_value=[]):
            events = [event async for event in ai_chat.respond([{"role": "user", "content": "List tools"}])]
        self.assertLess(events.index(("activity", "generating_tool")), events.index(("activity", "list_tools")))
