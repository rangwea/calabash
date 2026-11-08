"""Malformed/context-only source must never replace a working preview."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from service.chat.agent_runtime import ToolRequestMiddleware
from service.tools import tool_bundles as bundles
from service.tools.source_integrity import MARKERS
from tests.test_vue_workspace import fixture


class SourceIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_virtual_write_rejects_placeholder_before_handler(self):
        middleware = ToolRequestMiddleware()
        for name, field in [('write_tool_file', 'content'), ('patch_tool_file', 'new')]:
            for marker in MARKERS:
                request = SimpleNamespace(tool_call={'id': 'test', 'name': name, 'args': {field: marker + ' not code]'}})
                handler = AsyncMock()
                result = await middleware.awrap_tool_call(request, handler)
                self.assertEqual('error', result.status)
                self.assertIn('source_placeholder_rejected', result.content)
                handler.assert_not_called()
        request = SimpleNamespace(tool_call={'id': 'test', 'name': 'patch_tool_file', 'args': {'old': MARKERS[0], 'new': '<template>Restored</template>'}})
        handler = AsyncMock(return_value='updated')
        self.assertEqual('updated', await middleware.awrap_tool_call(request, handler))

    def test_bad_delivery_keeps_saved_bundle_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'HOME': temporary}):
            files = fixture()
            first = bundles.write('demo', 'counter', files, chat_id='synthetic')
            for bad in [MARKERS[1] + ' Read current source.]', '   ', '<!-- <template>not a block</template> -->', 'Just a summary']:
                changed = {**files, 'frontend/App.vue': bad}
                with self.assertRaises(ValueError):
                    bundles.write('demo', 'counter', changed, first['revision'], 'synthetic')
                self.assertEqual(files, bundles.read('demo', 'counter', 'synthetic')['files'])
            changed = {**files, 'frontend/App.vue': '<template>Corrected source</template>'}
            bundles.write('demo', 'counter', changed, first['revision'], 'synthetic')
            self.assertEqual(changed, bundles.read('demo', 'counter', 'synthetic')['files'])

    def test_preexisting_corruption_stays_readable_for_targeted_repair(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'HOME': temporary}):
            files = fixture()
            bundles.write('demo', 'counter', files, chat_id='synthetic')
            path = bundles.directory('demo', 'counter', 'synthetic') / 'frontend/App.vue'
            path.write_text(MARKERS[1] + ' old damaged source]')
            damaged = bundles.read('demo', 'counter', 'synthetic')
            self.assertIn(MARKERS[1], damaged['files']['frontend/App.vue'])
            bundles.write('demo', 'counter', files, damaged['revision'], 'synthetic')
            self.assertEqual(files, bundles.read('demo', 'counter', 'synthetic')['files'])
