import copy
import json
import unittest

from service.chat.chat_context import MAX_HISTORY_CHARACTERS, _compact_tool_sources, prepare


class ChatContextCompactionTests(unittest.TestCase):
    def test_long_virtual_draft_snapshots_are_compacted(self):
        messages = [
            {"role": "user", "content": "Create draft"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "write", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"file_path": "/draft.py", "content": "# source\n" * 12000})}}]},
            {"role": "tool", "tool_call_id": "write", "content": "Updated file /draft.py"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "read", "type": "function", "function": {"name": "read_file", "arguments": '{"file_path":"/draft.py"}'}}]},
            {"role": "tool", "tool_call_id": "read", "content": "# source\n" * 12000},
        ]
        result = prepare(messages)
        self.assertLess(len(json.dumps(result)), MAX_HISTORY_CHARACTERS)
        self.assertEqual(2, sum(m["role"] == "tool" for m in result))
        self.assertEqual("# source\n" * 12000, messages[-1]["content"])
    def test_non_thinking_budget_does_not_count_large_hidden_reasoning(self):
        messages = [
            {"role": "user", "content": "Create a ledger"},
            {"role": "assistant", "content": "I will create it", "reasoning_content": "thought " * 30000},
        ]
        result = prepare(messages, include_reasoning=False)
        self.assertNotIn("reasoning_content", result[-1])
        self.assertEqual(result[-1]["content"], "I will create it")
        self.assertEqual(len(messages[-1]["reasoning_content"]), 240000)

    def test_failed_and_unexecuted_source_is_preserved(self):
        call = {"id": "draft", "type": "function", "function": {"name": "write_tool", "arguments": '{"content":"unfinished draft"}'}}
        messages = [{"role": "assistant", "content": None, "tool_calls": [call]}]
        self.assertEqual(_compact_tool_sources(messages, 60000)[0], messages)
        messages.append({"role": "tool", "tool_call_id": "draft", "content": '{"error":"SyntaxError"}'})
        self.assertEqual(_compact_tool_sources(messages, 60000)[0], messages)

    def test_large_executed_tool_source_does_not_reject_small_request(self):
        messages = [{"role": "user", "content": "Create a ledger"}]
        for index, name in enumerate(("validate_tool", "write_tool", "preview_tool")):
            messages.extend([
                {"role": "assistant", "content": None, "tool_calls": [{
                    "id": str(index), "type": "function", "function": {
                        "name": name, "arguments": json.dumps({
                            "project": "demo", "name": "ledger", "content": "# code\n" * 12000,
                        }),
                    },
                }]},
                {"role": "tool", "tool_call_id": str(index), "content": json.dumps({"success": True, "url": "/preview/demo/ledger"})},
            ])
        original = copy.deepcopy(messages)
        result = prepare(messages)
        self.assertLess(len(json.dumps(result)), MAX_HISTORY_CHARACTERS)
        self.assertEqual(messages, original)
        self.assertEqual(sum(item["role"] == "tool" for item in result), 3)
        self.assertEqual(result[-1]["content"], messages[-1]["content"])

    def test_large_read_keeps_revision_and_call_pair(self):
        messages = [
            {"role": "user", "content": "Edit my tool"},
            {"role": "assistant", "content": None, "reasoning_content": "Read first", "tool_calls": [{"id": "read", "type": "function", "function": {"name": "read_tool", "arguments": '{"project":"demo","name":"ledger"}'}}]},
            {"role": "tool", "tool_call_id": "read", "content": json.dumps({"content": "x" * 90000, "revision": "abc"})},
        ]
        result = prepare(messages)
        self.assertEqual(json.loads(result[-1]["content"])["revision"], "abc")
        self.assertEqual(result[-2]["reasoning_content"], "Read first")
        self.assertEqual(result[-1]["tool_call_id"], result[-2]["tool_calls"][0]["id"])

    def test_small_context_unchanged_and_oversize_user_still_bounded(self):
        messages = [{"role": "user", "content": "Hello"}]
        self.assertEqual(prepare(messages), messages)
        with self.assertRaises(ValueError):
            prepare([{"role": "user", "content": "x" * (MAX_HISTORY_CHARACTERS + 1)}])
