import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch

from service.chat import agent_policy, agent_usage
from service.chat.code_inspection import inspect_source


class SourceInspectionTests(unittest.TestCase):
    def test_nested_callback_map_and_symbol_reads(self):
        source = 'def main():\n    def play():\n        return "synthetic"\n    return play\n'
        result = inspect_source(source, 'outline_code')
        self.assertEqual(['main', 'main.play'], [s['symbol'] for s in result['symbols']])
        callback = inspect_source(source, 'read_code_symbol', symbol='main.play', limit=1)
        self.assertEqual('2:     def play():', callback['content'])
        self.assertEqual(1, callback['next_offset'])
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), result['revision'])

    def test_literal_search_and_bounds(self):
        source = 'def main():\n    value = "file://synthetic"\n'
        self.assertEqual(2, inspect_source(source, 'search_code', query='file://')['matches'][0]['line'])
        self.assertEqual([], inspect_source(source, 'search_code', query='.*')['matches'])
        self.assertIn('error', inspect_source(source, 'outline_code', limit=121))
        self.assertIn('error', inspect_source(source, 'read_code_symbol', symbol='missing'))
        self.assertEqual('SyntaxError', inspect_source('def broken(', 'outline_code')['error'])
        huge = 'def main():\n    value = "' + 'x' * 20000 + '"\n'
        self.assertLessEqual(len(inspect_source(huge, 'read_code_symbol', symbol='main')['content']), 16000)

    def test_policy_pins_user_requirements(self):
        self.assertIn("Vue", agent_policy.system_prompt())
        anchor = agent_policy.task_anchor([{'role':'user','content':'Preserve blue UI'},{'role':'user','content':'Repair playback'}])
        self.assertIn("Preserve blue UI", anchor)
        self.assertIn("Repair playback", anchor)

class UsageTests(unittest.TestCase):
    def test_usage_normalization_and_missing_is_not_zero(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'HOME': directory}):
            usage = {}
            agent_usage.observe({'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'prompt_cache_hit_tokens': 60, 'prompt_cache_miss_tokens': 40}}, usage)
            agent_usage.record('one', 'run', 'model', 'deepseek', 'synthetic', 'completed', 12, 3, usage)
            agent_usage.record('two', 'run', 'summary', 'deepseek', 'synthetic', 'failed', 5, None, {})
            result = agent_usage.summary('run')
            self.assertEqual(0.6, result['cache_hit_rate'])
            self.assertEqual(1, result['usage_reported_requests'])
            self.assertEqual(2, result['requests'])
            self.assertEqual(1, result['summary_requests'])
            self.assertEqual('unknown', result['runtime_verification'])
            self.assertIsNone(agent_usage.summary('missing')['input_tokens'])
            anthropic = {}
            agent_usage.observe({'message': {'usage': {'input_tokens': 5, 'cache_read_input_tokens': 10, 'cache_creation_input_tokens': 15}}}, anthropic)
            agent_usage.observe({'usage': {'output_tokens': 8}}, anthropic)
            self.assertEqual(30, anthropic['input_tokens'])
            self.assertEqual(8, anthropic['output_tokens'])
            agent_usage.delete_runs(['run'])
            self.assertEqual(0, agent_usage.summary('run')['requests'])
