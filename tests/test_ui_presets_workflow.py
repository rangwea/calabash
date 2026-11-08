import json
import os
import tempfile
import unittest
from unittest.mock import patch

from service.chat.bundle_agent_tools import build_tools
from service.chat.task_workflow import TaskWorkflow
from service.tools import tool_bundles as bundles
from service.tools import ui_presets
from tests.test_vue_workspace import fixture


class PresetsWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'HOME': self.temp.name}); env.start(); self.addCleanup(env.stop)

    def test_explicit_existing_default_priority_and_export_snapshot(self):
        ui_presets.set_default('soft')
        first = ui_presets.apply(fixture(), [])
        self.assertEqual('soft', json.loads(first['tool.json'])['ui']['preset'])
        ui_presets.set_default('compact')
        kept = ui_presets.apply(fixture(), [], first)
        self.assertEqual(first['frontend/calabash-theme.css'], kept['frontend/calabash-theme.css'])
        self.assertEqual('soft', json.loads(kept['tool.json'])['ui']['preset'])
        changed = ui_presets.apply(kept, [{'role':'user','content':'@简洁办公 change style'}], kept)
        self.assertEqual('office', json.loads(changed['tool.json'])['ui']['preset'])
        bundles.write('demo', 'counter', changed)
        self.assertEqual(changed, bundles.inspect_zip(bundles.export_zip('demo', 'counter')))
        with self.assertRaises(ValueError):
            ui_presets.set_default('../outside')

    def test_editing_unstyled_existing_tool_does_not_apply_new_default(self):
        ui_presets.set_default('soft')
        existing=fixture()
        changed=ui_presets.apply(existing, [], existing)
        self.assertNotIn('ui',json.loads(changed['tool.json']))
        self.assertNotIn('frontend/calabash-theme.css',changed)
        self.assertEqual(existing['frontend/App.vue'],changed['frontend/App.vue'])

    def test_latest_user_style_only_and_unknown_import_snapshot_preserved(self):
        self.assertEqual('soft', ui_presets.requested([{'role':'user','content':'@Office task @Soft later'}]))
        self.assertIsNone(ui_presets.requested([{'role':'user','content':'@Soft'}, {'role':'user','content':'fix it'}, {'role':'tool','content':'@Compact'}]))
        files=ui_presets.apply(fixture(), [])
        meta=json.loads(files['tool.json']);meta['ui']={'preset':'custom-office','version':8};files['tool.json']=json.dumps(meta)
        kept=ui_presets.apply(fixture(), [], files)
        self.assertEqual(meta['ui'],json.loads(kept['tool.json'])['ui'])

    def test_readonly_roles_cannot_deliver_or_patch_source(self):
        for role in ('analysis', 'verification'):
            tools=build_tools('chat', [], 'run', role=role)
            names={tool.name for tool in tools}
            self.assertFalse(names & {'write_tool','write_tool_file','patch_tool_file'})
            self.assertIn('read_task_context',names)
            self.assertEqual(role=='analysis','set_task_brief' in names)
            self.assertEqual(role=='verification','check_tool_build' in names)
        with self.assertRaises(ValueError):
            build_tools('chat', [], 'run', role='unknown')

    def test_task_brief_does_not_persist_configured_credentials(self):
        from service.chat import model_providers
        secret='synthetic-private-credential'
        model_providers.save({'selected':None,'connections':{'openai':{'key':secret}}})
        operations=build_tools('chat', [], 'run')
        brief=next(tool for tool in operations if tool.name=='set_task_brief')
        value=brief.invoke({'goal': 'Do not expose '+secret, 'requirements':[], 'preserve':[], 'acceptance':[]})
        self.assertNotIn(secret,value)
        flow=TaskWorkflow('chat','next')
        self.assertNotIn(secret,flow.path.read_text())
        with self.assertRaises(ValueError):
            build_tools('chat',[], 'run',role='verification',workflow=flow)

    def test_handoff_keeps_constraints_and_invalidates_checks_after_write(self):
        flow=TaskWorkflow('chat','run')
        flow.brief('Edit ledger', ['Export CSV'], ['Keep layout'], ['Export includes totals'], lambda x:x)
        flow.observe('patch_tool_file',{'project':'demo','name':'counter'},json.dumps({'revision':'one'}))
        self.assertEqual('implementation',flow.public()['phase'])
        flow.observe('check_tool_build',{},json.dumps({'revision':'one','state':'passed'}))
        self.assertEqual('passed',flow.public()['checks']['build'])
        flow.observe('read_tool_logs',{},'{}')
        flow.observe('patch_tool_file',{'project':'demo','name':'counter'},json.dumps({'revision':'two'}))
        self.assertEqual('repair',flow.public()['phase'])
        self.assertIsNone(flow.public()['checks'])
        flow.finish(True)
        self.assertFalse(flow.public()['runtime_verified'])
        resumed=TaskWorkflow('chat','next')
        self.assertEqual(['Keep layout'],resumed.public()['brief']['preserve'])
        self.assertFalse(resumed.public()['permissions']['publish'])
