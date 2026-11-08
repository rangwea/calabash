"""Tool-library migration uses synthetic ZIPs, no source execution or model calls."""
import base64
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

from service.tools import harness_library as library
from service.tools import harness_workspace as workspace
from service.tools import tool_bundles as bundles
from tests.test_vue_workspace import fixture


class LibraryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'HOME': self.temp.name})
        self.env.start()
        library._tickets.clear()
        self.files = fixture()
        bundles.write('demo', 'counter', self.files)

    async def asyncTearDown(self):
        library._tickets.clear()
        workspace.release('test-session')
        self.env.stop()
        self.temp.cleanup()

    async def call(self, operation, **arguments):
        return await library.dispatch(operation, arguments)

    async def prepare(self, data=None):
        data = data or bundles.export_zip('demo', 'counter')
        ticket = (await self.call('begin'))['ticket']
        for offset in range(0, len(data), library.CHUNK):
            await self.call('upload', ticket=ticket, offset=offset,
                            data=base64.b64encode(data[offset:offset + library.CHUNK]).decode())
        return ticket, await self.call('inspect', ticket=ticket)

    async def test_export_roundtrip_contains_only_source(self):
        archive = await self.call('export', project='demo', name='counter')
        data = bytearray()
        while len(data) < archive['size']:
            chunk = await self.call('read', ticket=archive['ticket'], offset=len(data))
            data.extend(base64.b64decode(chunk['data']))
        self.assertEqual(self.files, bundles.inspect_zip(bytes(data)))
        await self.call('discard', ticket=archive['ticket'])
        with self.assertRaises(ValueError):
            await self.call('read', ticket=archive['ticket'], offset=0)

    async def test_inspection_never_builds_and_import_requires_confirmation(self):
        with patch.object(library, 'build_bundle', new=AsyncMock()) as build:
            ticket, inspected = await self.prepare()
            self.assertEqual('counter', inspected['manifest']['name'])
            self.assertEqual(bundles.revision(self.files), inspected['revision'])
            with self.assertRaises(ValueError):
                await self.call('import', ticket=ticket, revision=inspected['revision'], confirmed=False)
            build.assert_not_awaited()

    async def test_open_tool_blocks_replacement_before_build(self):
        ticket, inspected = await self.prepare()
        with patch.object(library.workers, 'is_open', return_value=True), patch.object(library, 'build_bundle', new=AsyncMock()) as build:
            with self.assertRaises(ValueError):
                await self.call('import', ticket=ticket, revision=inspected['revision'], confirmed=True)
            build.assert_not_awaited()

    async def test_confirmed_import_and_stale_overwrite(self):
        ticket, inspected = await self.prepare()
        built = Path(self.temp.name) / 'built'
        (built / 'dist').mkdir(parents=True)
        (built / 'dist/index.html').write_text('<html>synthetic</html>')
        with patch.object(library, 'build_bundle', new=AsyncMock(return_value=built)):
            with self.assertRaises(ValueError):
                await self.call('import', ticket=ticket, revision='stale', confirmed=True)
            await self.call('import', ticket=ticket, revision=inspected['revision'], confirmed=True)
        self.assertEqual(self.files, bundles.read('demo', 'counter')['files'])
        self.assertNotIn(ticket, library._tickets)

    async def test_delete_checks_confirmation_revision_and_open_state(self):
        for confirmed, revision in [(False, bundles.revision(self.files)), (True, 'stale')]:
            with self.assertRaises(ValueError):
                await self.call('delete', project='demo', name='counter', revision=revision, confirmed=confirmed)
        with patch.object(library.workers, 'is_open', return_value=True), self.assertRaises(ValueError):
            await self.call('delete', project='demo', name='counter', revision=bundles.revision(self.files), confirmed=True)
        await self.call('delete', project='demo', name='counter', revision=bundles.revision(self.files), confirmed=True)
        self.assertEqual([], bundles.list_tools())

    async def test_conversation_binding_survives_new_reads(self):
        self.assertIsNone(await self.call('conversation', project='demo', name='counter', session=None))
        await self.call('conversation', project='demo', name='counter', session='test-session')
        self.assertEqual('test-session', await self.call('conversation', project='demo', name='counter', session=None))
        self.assertEqual({'project': 'demo', 'name': 'counter'}, workspace.state('test-session'))
        instructions = await workspace.agent_call('test-session', 'instructions-1', 'instructions', {})
        self.assertEqual(workspace.state('test-session'), instructions['target'])

    async def test_traversal_unknown_and_transfer_bounds(self):
        with self.assertRaises(ValueError):
            await self.call('shell', path='/')
        with self.assertRaises(ValueError):
            await self.call('export', project='..', name='counter')
        ticket = (await self.call('begin'))['ticket']
        with self.assertRaises(ValueError):
            await self.call('upload', ticket=ticket, offset=1, data='YQ==')
        with self.assertRaises(ValueError):
            await self.call('upload', ticket=ticket, offset=0, data='a' * (library.CHUNK * 2))
        data = io.BytesIO()
        with ZipFile(data, 'w') as archive:
            archive.writestr('../tool.json', '{}')
        with self.assertRaises(ValueError):
            await self.prepare(data.getvalue())

    async def test_pending_tickets_expire_and_are_bounded(self):
        ticket = (await self.call('begin'))['ticket']
        library._tickets[ticket]['expires'] = 0
        with self.assertRaises(ValueError):
            await self.call('inspect', ticket=ticket)
        for _ in range(4):
            await self.call('begin')
        with self.assertRaises(ValueError):
            await self.call('begin')
