"""Synthetic DSH sessions exercise the same draft/build/publication boundaries."""
import os
import tempfile
import unittest
from unittest.mock import patch

from service.tools import harness_workspace as workspace
from service.tools import tool_bundles as bundles
from service.tools import work_drafts
from tests.test_tool_bundles import fixture


class HarnessWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'HOME': self.home.name})
        self.env.start()
        self.counter = 0

    async def asyncTearDown(self):
        for session in ['a', 'b']:
            workspace.release(session)
        self.env.stop()
        self.home.cleanup()

    async def call(self, operation, session='a', **arguments):
        self.counter += 1
        return await workspace.agent_call(session, f'call-{self.counter}', operation, {'project': 'demo', 'name': 'counter', **arguments})

    async def create(self):
        for path, content in fixture().items():
            await self.call('write_tool_file', path=path, content=content)

    async def test_draft_creation_is_not_publication_or_execution(self):
        await self.create()
        self.assertEqual([], bundles.list_tools())
        self.assertEqual({'project': 'demo', 'name': 'counter'}, workspace.state('a'))
        source = work_drafts.snapshot('demo', 'counter')
        self.assertIn('frontend/calabash-theme.css', source['files'])
        self.assertEqual('preview', source['source'])

    async def test_preview_discovery_is_read_only_and_requires_complete_source(self):
        self.assertIsNone(workspace.binding('a')['preview_revision'])
        await self.call('write_tool_file', path='tool.json', content=fixture()['tool.json'])
        self.assertIsNone(workspace.binding('a')['preview_revision'])
        await self.create()
        with patch.object(workspace.checks, 'ensure') as build, patch.object(workspace.checks, 'passed_revision', return_value=work_drafts.snapshot('demo', 'counter')['revision']), patch.object(workspace.workers, 'open') as run:
            value = workspace.binding('a')
            self.assertEqual(work_drafts.snapshot('demo', 'counter')['revision'], value['preview_revision'])
            build.assert_not_called()
            run.assert_not_called()
        source = bundles.directory('demo', 'counter', 'workspace') / 'frontend/App.tsx'
        source.unlink()
        self.assertIsNone(workspace.binding('a')['preview_revision'])
        self.assertEqual([], bundles.list_tools())

    async def test_read_before_write_and_session_write_lease(self):
        await self.create()
        path = bundles.directory('demo', 'counter', 'workspace') / 'frontend/App.tsx'
        path.write_text(path.read_text() + '\n')
        with self.assertRaises(ValueError):
            await self.call('write_tool_file', path='frontend/App.tsx', content='export default function App(){return <main>Changed</main>}')
        await self.call('read_tool_file', path='frontend/App.tsx')
        with self.assertRaises(ValueError):
            await self.call('write_tool_file', session='b', path='frontend/App.tsx', content='export default function App(){return <main>Other</main>}')
        await self.call('patch_tool_file', path='frontend/App.tsx', old='Increment', new='Increase')
        self.assertIn('Increase', work_drafts.snapshot('demo', 'counter')['files']['frontend/App.tsx'])

    async def test_stale_fingerprint_rejected_after_another_session_edits(self):
        await self.create()
        await self.call('read_tool_file', path='frontend/App.tsx')
        workspace.release('a')
        await self.call('read_tool_file', session='b', path='frontend/App.tsx')
        await self.call('patch_tool_file', session='b', path='frontend/App.tsx', old='Increment', new='Increase')
        workspace.release('b')
        with self.assertRaises(ValueError):
            await self.call('write_tool_file', path='frontend/App.tsx', content='export default function App(){return <main>Stale</main>}')

    async def test_agent_cannot_run_publish_delete_or_read_arbitrary_paths(self):
        for operation in ['run', 'publish', 'delete', 'shell']:
            with self.assertRaises(ValueError):
                await self.call(operation)
        await self.create()
        with self.assertRaises(ValueError):
            await self.call('read_tool_file', path='../../secrets')
        with self.assertRaises(ValueError):
            await workspace.publish('a', '', '', False)

    async def test_replayed_save_is_not_applied_twice(self):
        args = {'project': 'demo', 'name': 'counter', 'path': 'tool.json', 'content': fixture()['tool.json']}
        first = await workspace.agent_call('a', 'same-call', 'write_tool_file', args)
        second = await workspace.agent_call('a', 'same-call', 'write_tool_file', args)
        self.assertEqual(first, second)
        with self.assertRaises(ValueError):
            workspace.bind('a', 'demo', 'other')

    async def test_style_selection_is_authoritative_and_theme_is_snapshotted(self):
        import json

        from service.tools import ui_presets
        ui_presets.set_default('compact')
        for index, (path, content) in enumerate(fixture().items()):
            await workspace.agent_call('a', f'soft-{index}', 'write_tool_file', {'project': 'demo', 'name': 'counter', 'path': path, 'content': content}, requested_preset='soft')
        saved = work_drafts.snapshot('demo', 'counter')['files']
        self.assertEqual('soft', json.loads(saved['tool.json'])['ui']['preset'])
        guide = await workspace.agent_call('a', 'style', 'read_ui_preset', {'preset': 'office'}, requested_preset='soft')
        self.assertEqual(('soft', 'mention'), (guide['id'], guide['selected_by']))
        ui_presets.set_default('office')
        inherited = await workspace.agent_call('a', 'inherit', 'read_ui_preset', {'preset': 'compact'})
        self.assertEqual(('soft', 'snapshot'), (inherited['id'], inherited['selected_by']))
        self.assertEqual(saved['frontend/calabash-theme.css'], inherited['tokens'])

    async def test_explicit_followup_style_updates_theme_even_without_model_manifest_edit(self):
        import json
        await self.create()
        await self.call('read_tool_file', path='frontend/App.tsx')
        await workspace.agent_call('a', 'restyle', 'patch_tool_file', {'project': 'demo', 'name': 'counter', 'path': 'frontend/App.tsx', 'old': 'Increment', 'new': 'Increase'}, requested_preset='compact')
        saved = work_drafts.snapshot('demo', 'counter')['files']
        self.assertEqual('compact', json.loads(saved['tool.json'])['ui']['preset'])
        self.assertIn('Increase', saved['frontend/App.tsx'])
        await self.call('read_tool_file', path='frontend/App.tsx')
        await self.call('patch_tool_file', path='frontend/App.tsx', old='Increase', new='Increment')
        self.assertEqual(saved['frontend/calabash-theme.css'], work_drafts.snapshot('demo', 'counter')['files']['frontend/calabash-theme.css'])

    async def test_bilingual_style_catalog_does_not_change_language_setting(self):
        from backend.harness_bridge import dispatch
        from core.i18n import language, set_language
        set_language('zh-CN')
        values = await dispatch('ui.presets', {})
        self.assertEqual('zh-CN', language())
        office = next(value for value in values if value['id'] == 'office')
        self.assertEqual('简洁办公', office['title'])
        self.assertEqual('Office', office['title_en'])
        self.assertNotEqual(office['description'], office['description_en'])

    async def test_unknown_style_is_rejected_before_any_file_write(self):
        with self.assertRaises(ValueError):
            await workspace.agent_call('a', 'bad-style', 'write_tool_file', {'project': 'demo', 'name': 'counter', 'path': 'tool.json', 'content': fixture()['tool.json']}, requested_preset='../outside')
        self.assertIsNone(workspace.state('a'))

    async def test_reference_reads_do_not_bind_create_drafts_or_take_write_lease(self):
        bundles.write('demo', 'reference', fixture('reference'))
        published = bundles.read('demo', 'reference')
        await self.call('read_tool', name='reference')
        await self.call('read_tool_file', name='reference', path='frontend/App.tsx')
        await self.call('read_api_contract', name='reference')
        self.assertIsNone(workspace.state('a'))
        self.assertFalse(bundles.directory('demo', 'reference', 'workspace').exists())
        work_drafts.claim('demo', 'reference', workspace.owner('b'))
        await self.create()
        self.assertEqual({'project': 'demo', 'name': 'counter'}, workspace.state('a'))
        self.assertEqual(published, bundles.read('demo', 'reference'))
        self.assertFalse(bundles.directory('demo', 'reference', 'workspace').exists())

    async def test_bound_conversation_can_read_references_but_cannot_write_another_tool(self):
        await self.create()
        bundles.write('demo', 'reference', fixture('reference'))
        await self.call('read_tool', name='reference')
        await self.call('read_tool_file', name='reference', path='frontend/App.tsx')
        await self.call('read_tool_template', name='reference')
        result = await self.call('write_tool_file', name='reference', path='tool.json', content=fixture('reference')['tool.json'])
        self.assertFalse(result['saved'])
        self.assertEqual('tool_binding_conflict', result['error'])
        self.assertEqual('new_tool_conversation', result['next_action'])
        self.assertEqual({'project': 'demo', 'name': 'counter'}, workspace.state('a'))
        self.assertEqual({'project': 'demo', 'name': 'reference'}, workspace.binding('a')['conflict'])
        self.assertFalse(bundles.directory('demo', 'reference', 'workspace').exists())
        workspace.release('a')
        self.assertIsNone(workspace.binding('a')['conflict'])

    async def test_failed_first_write_does_not_bind_conversation(self):
        with self.assertRaises(ValueError):
            await self.call('write_tool_file', path='frontend/App.tsx', content='This is not source code')
        self.assertIsNone(workspace.state('a'))
        await self.call('write_tool_file', name='other', path='tool.json', content=fixture('other')['tool.json'])
        self.assertEqual({'project': 'demo', 'name': 'other'}, workspace.state('a'))
        work_drafts.release(workspace.owner('a'))
