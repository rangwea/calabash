"""Durable working source, automatic conflicts and no virtual synchronization."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.tools import tool_bundles as bundles
from service.tools import work_drafts
from tests.test_tool_bundles import fixture


class WorkDraftTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        environment = patch.dict(os.environ, {'HOME': self.temporary.name, 'USERPROFILE': self.temporary.name})
        environment.start(); self.addCleanup(environment.stop)
        self.addCleanup(lambda: work_drafts.release('first'))
        self.addCleanup(lambda: work_drafts.release('second'))

    def test_published_source_is_copied_once_and_resume_keeps_edits(self):
        files = fixture(); bundles.write('demo', 'counter', files)
        source = work_drafts.ensure('demo', 'counter', 'first')
        path = 'frontend/App.tsx'
        work_drafts.observe('chat', 'demo', 'counter', path, source['files'][path])
        work_drafts.write_files('chat', 'first', 'demo', 'counter', {path: 'export default function App(){return <main>Edited</main>}'})
        work_drafts.release('first')
        resumed = work_drafts.ensure('demo', 'counter', 'second')
        self.assertEqual('export default function App(){return <main>Edited</main>}', resumed['files'][path])
        self.assertEqual(files, bundles.read('demo', 'counter')['files'])
        self.assertEqual(bundles.directory('demo', 'counter', 'chat'), bundles.directory('demo', 'counter', 'other'))
        # Host observations survive a new execution; no revision or reload step.
        work_drafts.write_files('chat', 'second', 'demo', 'counter', {path: 'export default function App(){return <main>Resumed</main>}'})

    def test_single_writer_and_external_change_never_overwrite_working_source(self):
        files = fixture(); bundles.write('demo', 'counter', files, chat_id='chat')
        path = 'frontend/App.tsx'
        work_drafts.observe('chat', 'demo', 'counter', path, files[path])
        work_drafts.claim('demo', 'counter', 'first')
        with self.assertRaisesRegex(ValueError, 'another conversation'):
            work_drafts.claim('demo', 'counter', 'second')
        target = bundles.directory('demo', 'counter', 'chat') / path
        target.write_text('export default function App(){return <main>Externally changed</main>}')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            work_drafts.write_files('chat', 'first', 'demo', 'counter', {path: 'export default function App(){return <main>Stale</main>}'})
        self.assertEqual('export default function App(){return <main>Externally changed</main>}', target.read_text())
        work_drafts.release('first')
        work_drafts.observe('other', 'demo', 'counter', path, target.read_text())
        work_drafts.write_files('other', 'second', 'demo', 'counter', {path: 'export default function App(){return <main>New owner</main>}'})

    def test_partial_new_source_is_durable_and_symlinks_cannot_escape(self):
        work_drafts.write_files('chat', 'first', 'demo', 'counter', {'backend/main.py': 'def setup('})
        work_drafts.release('first')
        self.assertEqual('def setup(', work_drafts.ensure('demo', 'counter', 'second')['files']['backend/main.py'])
        with self.assertRaises(ValueError):
            work_drafts.write_files('chat', 'second', 'demo', 'counter', {'../outside.py': 'bad'})
        outside = Path(self.temporary.name) / 'outside.py'; outside.write_text('untouched')
        (bundles.directory('demo', 'counter', 'chat') / 'backend/link.py').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            work_drafts.snapshot('demo', 'counter')
        self.assertEqual('untouched', outside.read_text())


    def test_manifest_identity_and_case_collisions_are_rejected_before_writes(self):
        import json
        files = fixture(); bundles.write('demo', 'counter', files, chat_id='chat')
        manifest = json.loads(files['tool.json']); manifest['name'] = 'different'
        work_drafts.observe('chat', 'demo', 'counter', 'tool.json', files['tool.json'])
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            work_drafts.write_files('chat', 'first', 'demo', 'counter', {'tool.json': json.dumps(manifest)})
        with self.assertRaisesRegex(ValueError, 'distinct'):
            work_drafts.write_files('chat', 'first', 'demo', 'counter', {'frontend/app.tsx': 'export default function App(){return <main>Wrong case</main>}'})
        self.assertEqual(files, work_drafts.snapshot('demo', 'counter')['files'])
