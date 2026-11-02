"""Synthetic, offline acceptance cases for the authoring contracts (no model quota)."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.chat import agent_policy, agent_usage, ai_chat
from service.chat.code_inspection import inspect_source
from service.chat.code_target import CodeTarget
from service.files import tool_inputs
from service.tools import preview_service
from tests import test_deep_agent as harness


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

    def test_policy_is_shared_and_task_is_bounded(self):
        self.assertIn('outline_code', agent_policy.system_prompt())
        preview_schema = next(s['function'] for s in ai_chat.schemas() if s['function']['name'] == 'preview_tool')
        self.assertIn('revision', preview_schema['parameters']['properties'])
        reference = __import__('service.tools.ui_reference', fromlist=['read_reference'])
        self.assertEqual(agent_policy.system_prompt(), reference.read_reference('agent-policy.md')['content'])
        anchor = agent_policy.task_anchor([{'role': 'user', 'content': 'Preserve blue UI'}, {'role': 'user', 'content': 'Repair playback'}])
        self.assertIn('Preserve blue UI', anchor)
        self.assertIn('Repair playback', anchor)
        self.assertLess(len(agent_policy.task_anchor([{'role': 'user', 'content': 'x' * 100000}])), 4000)
        root = agent_policy.POLICY.parent
        self.assertNotIn('Keep the local run guard', (root / 'quality-gate.md').read_text())
        for path in root.glob('*-tool.py'):
            self.assertNotIn('ui.run(', path.read_text())


class TargetBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for target, value in [('app_dir', self.root), ('tools_dir', self.root / 'tools')]:
            item = patch.object(ai_chat, target, return_value=value)
            item.start()
            self.addCleanup(item.stop)
        item = patch.dict(os.environ, {'HOME': str(self.root)})
        item.start()
        self.addCleanup(item.stop)
        for target, value in [('_TMP_DIR', self.root / 'previews'), ('_PREVIEW_META_DIR', self.root / 'previews/_meta')]:
            item = patch.object(preview_service, target, value)
            item.start()
            self.addCleanup(item.stop)
        self.published = ai_chat.tool_path('demo', 'player')
        self.published.parent.mkdir(parents=True)
        self.published.write_text('def main():\n    return "published-old-ui"\n')
        ai_chat.save_chat('chat', [{'role': 'user', 'content': 'Keep new UI'}])
        self.preview = preview_service.create_temporary_preview('def main():\n    return "preview-new-ui"\n')
        self.token = tool_inputs.create('chat', self.preview['key'], [], tool_key='tool:demo/player')
        self.url = self.preview['preview_url'] + '?context=' + self.token
        ai_chat.remember_preview('chat', self.url)
        self.args = {'project': 'demo', 'name': 'player'}

    def test_preview_edits_never_overwrite_published_tool(self):
        session = CodeTarget('run', 'chat')
        read = session.execute('read_tool', self.args)
        self.assertEqual('preview', read['source'])
        self.assertIn('preview-new-ui', read['content'])
        content = read['content'].replace('preview-new-ui', 'preview-new-ui-fixed')
        result = session.execute('write_tool', {**self.args, 'content': content, 'revision': read['revision']})
        self.assertTrue(result['requires_manual_run'])
        self.assertFalse(result['runtime_verified'])
        self.assertIn('published-old-ui', self.published.read_text())
        self.assertIn('preview-new-ui-fixed', preview_service.get_preview_file(self.preview['key']).read_text())

    def test_resume_pins_source_and_stale_revision_is_rejected(self):
        read = CodeTarget('run', 'chat').execute('read_tool', self.args)
        ai_chat.remember_preview('chat', '/preview/different?context=not-valid')
        same = CodeTarget('run', 'chat').execute('read_tool', self.args)
        self.assertEqual(read, same)
        path = preview_service.get_preview_file(self.preview['key'])
        path.write_text('def main():\n    return "external change"\n')
        result = CodeTarget('run', 'chat').execute('write_tool', {**self.args, 'content': read['content'], 'revision': read['revision']})
        self.assertIn('error', result)
        self.assertIn('external change', path.read_text())

    def test_broken_preview_can_be_read_and_repaired(self):
        preview_service.get_preview_file(self.preview['key']).write_text('def main(:')
        read = CodeTarget('syntax-run', 'chat').execute('read_tool', self.args)
        self.assertEqual('def main(:', read['content'])
        self.assertEqual('SyntaxError', inspect_source(read['content'], 'outline_code')['error'])
        result = CodeTarget('syntax-run', 'chat').execute('write_tool', {**self.args, 'content': 'def main():\n    pass\n', 'revision': read['revision']})
        self.assertTrue(result['success'])

    def test_foreign_preview_fails_closed(self):
        ai_chat.save_chat('other', [{'role': 'user', 'content': 'Other'}])
        ai_chat.remember_preview('other', self.url)
        with self.assertRaises(ValueError):
            CodeTarget('foreign-run', 'other').execute('read_tool', self.args)


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


class AuthoringBenchmarks(unittest.IsolatedAsyncioTestCase):
    setUp = harness.DeepAgentTests.setUp
    transport = harness.DeepAgentTests.transport
    active = harness.DeepAgentTests.active
    collect = harness.DeepAgentTests.collect

    async def test_real_adapter_records_reported_usage_and_chat_deletion_cleans_it(self):
        def script(data, n):
            return {**harness.answer(), 'usage': {'prompt_tokens': 100, 'completion_tokens': 12, 'prompt_cache_hit_tokens': 80, 'prompt_cache_miss_tokens': 20}}
        messages = [{'role': 'user', 'content': 'Synthetic usage'}]
        with self.active(), self.transport(script):
            await self.collect(messages, 'usage-benchmark')
        run_id = messages[0]['agent_checkpoint_id']
        result = agent_usage.summary(run_id)
        self.assertEqual(100, result['input_tokens'])
        self.assertEqual(12, result['output_tokens'])
        self.assertEqual(0.8, result['cache_hit_rate'])
        self.assertEqual(1, result['requests'])
        ai_chat.delete_chat('usage-benchmark')
        self.assertEqual(0, agent_usage.summary(run_id)['requests'])

    async def test_network_failure_is_accounted_without_recording_error_text(self):
        import httpx
        def script(data, n):
            raise httpx.ConnectError('synthetic-private-detail')
        messages = [{'role': 'user', 'content': 'Synthetic failure'}]
        with self.active(), self.transport(script), self.assertRaises(httpx.ConnectError):
            await self.collect(messages, 'failed-benchmark')
        result = agent_usage.summary(messages[0]['agent_checkpoint_id'])
        self.assertEqual(1, result['failed_requests'])
        self.assertIsNone(result['input_tokens'])
        with agent_usage.connect() as db:
            self.assertNotIn('synthetic-private-detail', str(db.execute('SELECT * FROM requests').fetchall()))

    async def test_compaction_keeps_task_and_accounts_for_summary(self):
        source = 'def main():\n    pass\n' + '# synthetic source\n' * 5000

        def script(data, n):
            if n == 1:
                return harness.call('write_file', {'file_path': '/large.py', 'content': source}, 'large')
            if n == 2:
                return harness.answer('Internal summary: draft exists.')
            self.assertIn('Preserve blue UI; repair playback only', data['messages'][0]['content'])
            return harness.answer('Saved, not runtime verified.')

        messages = [{'role': 'user', 'content': 'Preserve blue UI; repair playback only'}]
        with self.active(), self.transport(script):
            events = await self.collect(messages, 'compaction-benchmark')
        result = agent_usage.summary(messages[0]['agent_checkpoint_id'])
        self.assertEqual(3, result['requests'])
        self.assertEqual(1, result['summary_requests'])
        self.assertNotIn(('text', 'Internal summary: draft exists.'), events)
        self.assertEqual('unknown', result['runtime_verification'])

    async def test_locate_media_path_bug_without_rewriting_ui(self):
        source = 'def main():\n    theme = "blue-ui"\n    def audio_source(path):\n        return "file://" + path\n    return audio_source\n'
        target = self.root / '.calabash/tools/demo/player.py'
        target.parent.mkdir(parents=True)
        target.write_text(source)

        def script(data, n):
            args = {'project': 'demo', 'name': 'player'}
            if n == 1:
                return harness.call('outline_code', args, 'outline')
            if n == 2:
                return harness.call('read_code_symbol', {**args, 'symbol': 'main.audio_source'}, 'source')
            if n == 3:
                result = json.loads(data['messages'][-1]['content'])
                self.assertIn('file://', result['content'])
                return harness.call('stage_tool', args, 'stage')
            if n == 4:
                return harness.call('edit_file', {'file_path': '/drafts/demo/player.py', 'old_string': 'return "file://" + path', 'new_string': 'return "/synthetic-authorized-media/" + path'}, 'edit')
            if n == 5:
                revision = json.loads(next(m['content'] for m in data['messages'] if m.get('tool_call_id') == 'stage'))['revision']
                return harness.call('deliver_draft', {**args, 'file_path': '/drafts/demo/player.py', 'revision': revision, 'action': 'write_tool'}, 'save')
            return harness.answer('Saved; playback has not been verified.')

        messages = [{'role': 'user', 'content': 'Preserve blue UI and repair audio URL'}]
        with self.active(), self.transport(script):
            await self.collect(messages, 'benchmark')
        self.assertIn('blue-ui', target.read_text())
        self.assertNotIn('file://', target.read_text())
        usage = agent_usage.summary(messages[0]['agent_checkpoint_id'])
        self.assertEqual(6, usage['requests'])
        self.assertEqual(0, usage['failed_requests'])
        self.assertIsNone(usage['input_tokens'])  # Fake provider did not report usage.
        self.assertEqual('unknown', usage['runtime_verification'])
        self.assertIn('Pinned task context', self.requests[-1]['messages'][0]['content'])
        # A benchmark of host contracts, not evidence of real-model coding skill.
        self.assertFalse(any('synthetic-only-key' in str(m) for m in messages))
