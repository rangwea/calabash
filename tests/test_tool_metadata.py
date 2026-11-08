import json
import unittest

from service.tools.tool_bundles import validate
from tests.test_tool_bundles import fixture


class ToolMetadataTests(unittest.TestCase):
    def test_manifest_identity_and_capabilities(self):
        files = fixture()
        manifest = json.loads(files['tool.json'])
        manifest['requires'] = 'media.ffmpeg>=9.0.2'
        files['tool.json'] = json.dumps(manifest)
        self.assertEqual('demo', validate(files)['project'])
        manifest['requires'] = 'https://untrusted.invalid/install'
        files['tool.json'] = json.dumps(manifest)
        with self.assertRaises(ValueError):
            validate(files)
