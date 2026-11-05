"""Synthetic compiler, revision and publication cache regression tests."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.tools import tool_bundles as bundles
from service.tools.tool_checks import ToolChecks
from service.tools.tool_workers import FrontendBuildError, build_diagnostics
from tests.test_vue_workspace import fixture


class CheckTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'HOME': self.temp.name})
        env.start(); self.addCleanup(env.stop)
        self.checks = ToolChecks()
        self.addAsyncCleanup(self.checks.close)
        self.source = {'files': fixture(), 'revision': bundles.revision(fixture())}

    def artifact(self, name):
        root = Path(self.temp.name) / '.calabash/builds' / name
        (root / 'dist').mkdir(parents=True, exist_ok=True)
        (root / 'dist/index.html').write_text('compiled')
        return root

    async def test_concurrent_preview_and_publish_reuse_same_artifact(self):
        calls = []
        async def build(files):
            calls.append(files)
            await asyncio.sleep(.01)
            return self.artifact('one')
        with patch('service.tools.tool_checks.build_bundle', build):
            entry = self.checks.ensure('demo', 'counter', 'chat', self.source)
            self.assertEqual('checking', entry.public()['state'])
            self.assertIs(entry, self.checks.ensure('demo', 'counter', 'chat', self.source))
            async with self.checks.verified('demo', 'counter', 'chat', self.source) as root:
                self.assertEqual('passed', entry.state)
                self.assertEqual('compiled', (root / 'dist/index.html').read_text())
            self.assertEqual(1, len(calls))
            (root / 'dist/index.html').unlink()
            self.assertIsNot(entry, self.checks.ensure('demo', 'counter', 'chat', self.source))
            await asyncio.sleep(.02)

    async def test_failed_check_blocks_publish_and_explicit_retry_recovers(self):
        root = self.artifact('failed')
        (root / 'build.log').write_text('/private/user/frontend/App.vue(12,7): error TS2322: secret-literal\n')
        async def failed(files):
            raise FrontendBuildError(root)
        with patch('service.tools.tool_checks.build_bundle', failed):
            entry = self.checks.ensure('demo', 'counter', 'chat', self.source)
            await entry.task
            self.assertEqual('failed', entry.state)
            self.assertNotIn('secret-literal', str(entry.public()))
            with self.assertRaises(ValueError):
                async with self.checks.verified('demo', 'counter', 'chat', self.source):
                    self.fail('Failed build was published')
        async def build(files):
            return self.artifact('retry')
        with patch('service.tools.tool_checks.build_bundle', build):
            retry = self.checks.ensure('demo', 'counter', 'chat', self.source, retry=True)
            await retry.task
            self.assertEqual('passed', retry.state)

    def test_mismatched_compiler_input_cannot_poison_revision_cache(self):
        with self.assertRaises(ValueError):
            self.checks.ensure('demo', 'counter', 'chat', {**self.source, 'files': fixture('other')})
        self.assertFalse(self.checks.entries)

    async def test_source_and_compiler_versions_invalidate_results(self):
        async def build(files):
            return self.artifact(str(len(self.checks.entries)))
        with patch('service.tools.tool_checks.build_bundle', build), patch('service.tools.tool_checks.compiler_version', return_value='v1'):
            old = self.checks.ensure('demo', 'counter', 'chat', self.source)
            await old.task
            changed = {**self.source['files'], 'frontend/App.vue': '<template>New UI</template>'}
            source = {'files': changed, 'revision': bundles.revision(changed)}
            new = self.checks.ensure('demo', 'counter', 'chat', source)
            self.assertNotEqual(old.revision, new.revision)
            await new.task
            with patch('service.tools.tool_checks.compiler_version', return_value='v2'):
                rebuilt = self.checks.ensure('demo', 'counter', 'chat', source)
                self.assertIsNot(new, rebuilt)
                await rebuilt.task

    async def test_real_strict_compiler_reports_errors_then_builds(self):
        files = fixture()
        files['frontend/App.vue'] = '<script setup lang="ts">const count: number = "wrong"</script><template><p>{{count}}</p></template>'
        source = {'files': files, 'revision': bundles.revision(files)}
        entry = self.checks.ensure('demo', 'counter', 'chat', source)
        await entry.task
        self.assertEqual('failed', entry.state)
        issue = entry.diagnostics[0]
        self.assertEqual(('frontend/App.vue', 'TS2322', 1), (issue['file'], issue['code'], issue['line']))
        malformed = {**files, 'frontend/App.vue': '<template><div></template>'}
        bad = self.checks.ensure('demo', 'counter', 'chat', {'files': malformed, 'revision': bundles.revision(malformed)})
        await bad.task
        self.assertEqual('failed', bad.state)
        self.assertEqual('VITE', bad.diagnostics[0]['code'])
        self.assertEqual('frontend/App.vue', bad.diagnostics[0]['file'])
        files = {**files, 'frontend/App.vue': files['frontend/App.vue'].replace('"wrong"', '1')}
        source = {'files': files, 'revision': bundles.revision(files)}
        passed = self.checks.ensure('demo', 'counter', 'chat', source)
        await passed.task
        self.assertEqual('passed', passed.state, (passed.root / 'build.log').read_text() if passed.root else str(passed.public()))
        async with self.checks.verified('demo', 'counter', 'chat', source) as root:
            self.assertTrue((root / 'dist/index.html').is_file())

    async def test_saved_diagnostics_survive_cache_cleanup_without_changing_source(self):
        from service.tools.check_records import read as read_record
        files = fixture()
        saved = bundles.write('demo', 'counter', files, chat_id='chat')
        root = self.artifact('persisted')
        (root / 'build.log').write_text('frontend/App.vue(4,2): error TS2322: local-only-secret')
        async def build(files):
            raise FrontendBuildError(root)
        with patch('service.tools.tool_checks.build_bundle', build):
            entry = self.checks.ensure('demo', 'counter', 'chat', self.source)
            await entry.task
        await self.checks.close()
        record = read_record('demo', 'counter', 'chat', self.source['revision'])
        self.assertEqual('failed', record['state'])
        self.assertEqual(4, record['diagnostics'][0]['line'])
        self.assertNotIn('local-only-secret', str(record))
        self.assertEqual(saved['revision'], bundles.read('demo', 'counter', 'chat')['revision'])
        self.assertEqual(files, bundles.read('demo', 'counter', 'chat')['files'])
        self.assertEqual('unavailable', read_record('demo', 'counter', 'other-chat', self.source['revision'])['state'])

    def test_diagnostic_retention_and_symlink_boundaries(self):
        from service.tools.check_records import directory, read, record
        for index in range(8):
            revision = f'{index:064x}'
            record('demo', 'counter', 'chat', {'revision': revision, 'state': 'failed', 'diagnostics': []})
        path = directory('demo', 'counter', 'chat')
        self.assertEqual(5, len(list(path.glob('*.json'))))
        self.assertEqual('failed', read('demo', 'counter', 'chat', f'{7:064x}')['state'])
        self.assertEqual('unavailable', read('demo', 'counter', 'other', f'{7:064x}')['state'])
        other = path.parent / 'linked'
        other.symlink_to(path, target_is_directory=True)
        with self.assertRaises(ValueError):
            read('demo', 'counter', 'linked', f'{7:064x}')

    def test_diagnostics_do_not_return_arbitrary_paths_or_source_text(self):
        root = self.artifact('diagnostics')
        (root / 'build.log').write_text('frontend/../../secret.ts(1,1): error TS2322: token\nfrontend/App.vue(4,2): error TS2353: password\n')
        issues = build_diagnostics(root)
        self.assertEqual(1, len(issues))
        self.assertEqual('frontend/App.vue', issues[0]['file'])
        self.assertNotIn('password', str(issues))
