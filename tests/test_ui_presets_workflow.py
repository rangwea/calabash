import json
import os
import tempfile
import unittest
from unittest.mock import patch

from service.tools import tool_bundles as bundles
from service.tools import ui_presets
from tests.test_tool_bundles import fixture


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
        self.assertEqual(existing['frontend/App.tsx'],changed['frontend/App.tsx'])

    def test_latest_user_style_only_and_unknown_import_snapshot_preserved(self):
        self.assertEqual('soft', ui_presets.requested([{'role':'user','content':'@Office task @Soft later'}]))
        self.assertIsNone(ui_presets.requested([{'role':'user','content':'@Soft'}, {'role':'user','content':'fix it'}, {'role':'tool','content':'@Compact'}]))
        files=ui_presets.apply(fixture(), [])
        meta=json.loads(files['tool.json']);meta['ui']={'preset':'custom-office','version':8};files['tool.json']=json.dumps(meta)
        kept=ui_presets.apply(fixture(), [], files)
        self.assertEqual(meta['ui'],json.loads(kept['tool.json'])['ui'])
