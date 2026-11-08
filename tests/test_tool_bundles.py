"""Synthetic React tool bundle acceptance: no user files, models or installed App."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.tools import tool_bundles as bundles


def fixture(name='counter'):
    return {
        'tool.json': json.dumps({'format': 'calabash-react-tool', 'version': 1, 'project': 'demo', 'name': name, 'title': 'Counter'}),
        'frontend/App.tsx': 'import {useState} from "react";import {Button} from "antd";export default function App(){const [n,setN]=useState(0);return <main><h1>Count: {n}</h1><Button onClick={()=>setN(n+1)}>Increment</Button></main>}',
        'backend/main.py': 'def setup(app, sdk):\n    @app.get("/api/state")\n    def state():\n        return {"count": 0}\n',
    }


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'HOME': self.temp.name})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_index_only_includes_current_bundle_format(self):
        files = fixture()
        bundles.write('demo', 'counter', files)
        unrelated = bundles.directory('demo', 'single_file').with_suffix('.py')
        unrelated.write_text("raise RuntimeError('Must not execute')")
        self.assertEqual(['counter'], [tool['name'] for tool in bundles.list_tools()])
        with self.assertRaises(bundles.ToolUnavailable) as error:
            bundles.read('demo', 'single_file')
        self.assertEqual('tool_not_found', error.exception.code)

    def test_atomic_versions_preserve_current_source_on_conflict(self):
        files = fixture()
        first = bundles.write('demo', 'counter', files)
        changed = {**files, 'frontend/App.tsx': 'export default function App(){return <main>Changed</main>}'}
        with self.assertRaises(ValueError):
            bundles.write('demo', 'counter', changed)
        self.assertEqual(files, bundles.read('demo', 'counter')['files'])
        second = bundles.write('demo', 'counter', changed, first['revision'])
        self.assertNotEqual(first['revision'], second['revision'])

    def test_draft_does_not_replace_published_source(self):
        files = fixture(); bundles.write('demo', 'counter', files)
        changed = {**files, 'frontend/App.tsx': 'export default function App(){return <main>Draft</main>}'}
        bundles.write('demo', 'counter', changed, chat_id='chat')
        self.assertEqual(files, bundles.read('demo', 'counter')['files'])
        self.assertEqual(changed, bundles.read('demo', 'counter', 'chat')['files'])

    def test_archive_roundtrip_does_not_execute_backend(self):
        files = fixture(); bundles.write('demo', 'counter', files)
        data = bundles.export_zip('demo', 'counter')
        self.assertEqual(files, bundles.inspect_zip(data))

    def test_rejects_paths_scripts_symlinks_and_duplicate_zip_entries(self):
        for path in ['../tool.json', '/tool.json', 'frontend/../x.vue', 'frontend\\x.vue', 'package.json', 'frontend/node_modules/x.ts']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                bundles.safe_path(path)
        path = bundles.directory('demo', 'counter')
        path.parent.mkdir(parents=True)
        path.symlink_to(Path(self.temp.name), target_is_directory=True)
        with self.assertRaises(ValueError):
            bundles.read('demo', 'counter')

    def test_invalid_manifest_or_backend_rejected_before_write(self):
        for key, value in [('tool.json', '{}'), ('backend/main.py', 'def setup(app,sdk) pass'), ('backend/main.py', 'def main(): pass')]:
            with self.subTest(key=key), self.assertRaises((ValueError, SyntaxError)):
                bundles.write('demo', 'counter', {**fixture(), key: value})
        self.assertFalse(bundles.directory('demo', 'counter').exists())
