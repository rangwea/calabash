import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.chat import model_providers as models


class ProviderTests(unittest.TestCase):
    def test_independent_keys(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(models, "app_dir", return_value=Path(directory)):
            data = models.load()
            self.assertEqual({"selected": None, "connections": {}}, data)
            data["connections"]["deepseek"] = {"key": "deepseek-key", "models": ["model-version"], "base_url": "https://api.deepseek.com"}
            data["connections"]["anthropic"] = {"key": "claude-key", "models": ["snapshot"], "base_url": "https://api.anthropic.com/v1"}
            models.save(data)
            models.select("anthropic::snapshot")
            provider, model, connection = models.active()
            self.assertEqual(("anthropic", "snapshot", "claude-key"), (provider, model, connection["key"]))
            self.assertIn("deepseek::model-version", models.options())
            self.assertEqual(0o600, (Path(directory) / "model_connections.json").stat().st_mode & 0o777)

    def test_claude_tool_roundtrip(self):
        messages = [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "create"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call1", "function": {"name": "list_tools", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call1", "content": "[]"},
        ]
        url, headers, payload = models.request("anthropic", "snapshot", {"key": "secret", "base_url": "https://api.anthropic.com/v1"}, messages, [])
        self.assertTrue(url.endswith("/v1/messages"))
        self.assertEqual("secret", headers["x-api-key"])
        self.assertEqual("tool_use", payload["messages"][1]["content"][0]["type"])
        self.assertEqual("call1", payload["messages"][2]["content"][0]["tool_use_id"])
        event = {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{}"}}
        self.assertEqual("{}", models.normalize(event, "anthropic")["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"])

    def test_compatible_provider_request(self):
        for provider in ("deepseek", "openai", "qwen"):
            url, headers, payload = models.request(provider, "model-version", {"base_url": models.PROVIDERS[provider][1], "key": "secret"}, [], [])
            self.assertTrue(url.endswith("/chat/completions"))
            self.assertEqual("Bearer secret", headers["Authorization"])
            self.assertTrue(payload["stream"])

    def test_deepseek_reasoning_is_replayed_only_for_deepseek(self):
        messages = [{"role": "assistant", "content": "done", "reasoning_content": "reasoning"}]
        connection = {"base_url": "https://example.test", "key": "secret"}
        _, _, payload = models.request("deepseek", "model", connection, messages, [])
        self.assertEqual("reasoning", payload["messages"][0]["reasoning_content"])
        _, _, payload = models.request("openai", "model", connection, messages, [])
        self.assertNotIn("reasoning_content", payload["messages"][0])
        # Switching from another current provider must not fabricate DeepSeek reasoning.
        _, _, payload = models.request("deepseek", "model", connection, [{"role": "assistant", "content": "answer from another model"}], [])
        self.assertEqual({"type": "disabled"}, payload["thinking"])
