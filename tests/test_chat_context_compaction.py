import copy
import json
import unittest

from service.chat.chat_context import (
    MAX_HISTORY_CHARACTERS,
    _compact_tool_sources,
    prepare,
)


class ChatContextCompactionTests(unittest.TestCase):
    def test_long_working_source_snapshots_are_compacted(self):
        messages = [
            {"role": "user", "content": "Create draft"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "write", "type": "function", "function": {"name": "write_tool_file", "arguments": json.dumps({"path": "backend/helpers.py", "content": "# source\n" * 12000})}}]},
            {"role": "tool", "tool_call_id": "write", "content": "Updated file backend/helpers.py"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "read", "type": "function", "function": {"name": "read_tool_file", "arguments": '{"path":"backend/helpers.py"}'}}]},
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
        for index, name in enumerate(("write_tool_file", "write_tool", "patch_tool_file")):
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

    def test_followup_repair_keeps_ui_request_by_compacting_prior_code(self):
        requirement = 'Use the new blue sidebar and compact cards; preserve this UI.'
        messages = [
            {'role': 'user', 'content': requirement},
            {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'save', 'type': 'function', 'function': {'name': 'write_tool', 'arguments': json.dumps({'project': 'demo', 'name': 'ui', 'content': '# source\n' * 15000})}}]},
            {'role': 'tool', 'tool_call_id': 'save', 'content': json.dumps({'saved': 'synthetic'})},
            {'role': 'assistant', 'content': 'The new UI is saved.'},
            {'role': 'user', 'content': 'Repair the current error without changing the UI.'},
        ]
        original = copy.deepcopy(messages)
        compacted = prepare(messages, include_reasoning=False)
        self.assertIn(requirement, [m.get('content') for m in compacted])
        self.assertIn('The new UI is saved.', [m.get('content') for m in compacted])
        self.assertEqual(messages, original)
        self.assertLess(len(json.dumps(compacted)), MAX_HISTORY_CHARACTERS)

    def test_small_context_unchanged_and_oversize_user_still_bounded(self):
        messages = [{"role": "user", "content": "Hello"}]
        self.assertEqual(prepare(messages), messages)
        with self.assertRaises(ValueError):
            prepare([{"role": "user", "content": "x" * (MAX_HISTORY_CHARACTERS + 1)}])

    def test_latest_read_survives_large_context_and_is_paged(self):
        messages = [{'role': 'user', 'content': 'Repair current tool'}]
        for index in range(4):
            messages.extend([
                {'role': 'assistant', 'tool_calls': [{'id': str(index), 'function': {'name': 'read_tool_file', 'arguments': '{"path":"frontend/App.vue","offset":0}'}}]},
                {'role': 'tool', 'tool_call_id': str(index), 'content': 'const current = true;\n' * 4000},
            ])
        original = copy.deepcopy(messages)
        compact, _ = _compact_tool_sources(messages, 40000)
        self.assertTrue(compact[-1]['content'].startswith('const current = true;'))
        self.assertIn('offset=', compact[-1]['content'])
        self.assertNotIn('read omitted', compact[-1]['content'])
        self.assertLess(len(json.dumps(compact)), 40000)
        self.assertEqual(messages, original)

    def test_latest_structured_read_keeps_lines_revision_and_next_offset(self):
        payload = {'path': 'frontend/App.vue', 'revision': 'current', 'lines': [
            {'line': index + 31, 'text': 'const current = true;' * 25} for index in range(150)]}
        messages = [
            {'role': 'assistant', 'tool_calls': [{'id': 'read', 'function': {'name': 'read_tool_file', 'arguments': '{"offset":30}'}}]},
            {'role': 'tool', 'tool_call_id': 'read', 'content': json.dumps(payload)},
        ]
        compact, _ = _compact_tool_sources(messages, 40000)
        result = json.loads(compact[-1]['content'])
        self.assertEqual('current', result['revision'])
        self.assertTrue(result['truncated'])
        self.assertEqual(result['lines'][-1]['line'], result['next_offset'])
        self.assertIsInstance(result['lines'], list)
        self.assertLess(len(json.dumps(compact)), 40000)

    def test_current_read_is_not_trimmed_when_old_write_can_be_released(self):
        content = 'current line\n' * 1800
        messages = [
            {'role': 'assistant', 'tool_calls': [{'id': 'write', 'function': {'name': 'write_tool_file', 'arguments': json.dumps({'content': 'old source' * 10000})}}]},
            {'role': 'tool', 'tool_call_id': 'write', 'content': 'Updated'},
            {'role': 'assistant', 'tool_calls': [{'id': 'read', 'function': {'name': 'read_tool_file', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'read', 'content': content},
        ]
        compact, _ = _compact_tool_sources(messages, 40000)
        self.assertEqual(content, compact[-1]['content'])

    def test_repeated_paging_retains_complete_small_working_file(self):
        messages = [{'role': 'user', 'content': 'Fix one function without rereading the file'}]
        for repeat in range(5):
            for offset in (0, 130, 260, 390):
                call_id = f'{repeat}-{offset}'
                content = '\n'.join(f'{line+1:3}  source_line_{line}' for line in range(offset, min(offset+130, 497)))
                messages.extend([
                    {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {'name': 'read_tool_file', 'arguments': json.dumps({'path': 'backend/main.py', 'offset': offset, 'limit': 130})}}]},
                    {'role': 'tool', 'tool_call_id': call_id, 'content': content},
                ])
        compact, _ = _compact_tool_sources(messages, 40000)
        contents = '\n'.join(item.get('content', '') for item in compact if item['role'] == 'tool')
        for line in range(497):
            self.assertIn(f'source_line_{line}\n', contents + '\n')
        self.assertLess(len(json.dumps(compact)), 40000)
