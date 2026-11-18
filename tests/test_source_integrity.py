"""Malformed/context-only source must never replace a working preview."""
import os
import tempfile
import unittest
from unittest.mock import patch

from service.tools import tool_bundles as bundles
from service.tools.source_integrity import MARKERS
from tests.test_tool_bundles import fixture


class SourceIntegrityTests(unittest.IsolatedAsyncioTestCase):

    def test_bad_delivery_keeps_saved_bundle_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'HOME': temporary, 'USERPROFILE': temporary}):
            files = fixture()
            first = bundles.write('demo', 'counter', files, chat_id='synthetic')
            for bad in [MARKERS[1] + ' Read current source.]', '   ', '<!-- export default function App(){return <main>not a block</main>} -->', 'Just a summary']:
                changed = {**files, 'frontend/App.tsx': bad}
                with self.assertRaises(ValueError):
                    bundles.write('demo', 'counter', changed, first['revision'], 'synthetic')
                self.assertEqual(files, bundles.read('demo', 'counter', 'synthetic')['files'])
            changed = {**files, 'frontend/App.tsx': 'export default function App(){return <main>Corrected source</main>}'}
            bundles.write('demo', 'counter', changed, first['revision'], 'synthetic')
            self.assertEqual(changed, bundles.read('demo', 'counter', 'synthetic')['files'])

    def test_preexisting_corruption_stays_readable_for_targeted_repair(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'HOME': temporary, 'USERPROFILE': temporary}):
            files = fixture()
            bundles.write('demo', 'counter', files, chat_id='synthetic')
            path = bundles.directory('demo', 'counter', 'synthetic') / 'frontend/App.tsx'
            path.write_text(MARKERS[1] + ' old damaged source]')
            damaged = bundles.read('demo', 'counter', 'synthetic')
            self.assertIn(MARKERS[1], damaged['files']['frontend/App.tsx'])
            bundles.write('demo', 'counter', files, damaged['revision'], 'synthetic')
            self.assertEqual(files, bundles.read('demo', 'counter', 'synthetic')['files'])
