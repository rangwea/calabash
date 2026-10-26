import base64
import hashlib
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from service.capabilities.capability_manifest import PackError
from service.capabilities.capability_packs import PackManager


class CapabilityPackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.key = Ed25519PrivateKey.generate()
        self.manager = PackManager(self.directory / 'plugins',
            public_keys=(self.key.public_key().public_bytes_raw(),), target='macos-arm64',
            selfchecks={'media.ffmpeg': lambda *args: True})

    def bundle(self, version='1.0.0', filename='bin/ffmpeg', mutate=None):
        data = b'synthetic engine'
        buffer = BytesIO()
        with ZipFile(buffer, 'w') as archive:
            archive.writestr(filename, data)
        payload = buffer.getvalue()
        package = {'id': 'media.ffmpeg', 'version': version, 'platform': 'macos-arm64', 'protocol': 1,
            'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(), 'expanded_size': len(data),
            'files': [{'path': filename, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'executable': True}],
            'entries': {'ffmpeg': filename}, 'operations': ['probe'], 'license': 'test', 'source': 'GitHub release'}
        if mutate:
            mutate(package)
        raw = json.dumps({'schema_version': 1, 'packages': [package]}).encode()
        envelope = {'payload': base64.b64encode(raw).decode(),
            'signature': base64.b64encode(self.key.sign(raw)).decode()}
        path = self.directory / 'plugin.zip'
        with ZipFile(path, 'w') as archive:
            archive.writestr('manifest.json', json.dumps(envelope))
            archive.writestr('payload.zip', payload)
        return path

    def assert_code(self, code, action):
        with self.assertRaises(PackError) as caught:
            action()
        self.assertEqual(code, caught.exception.code)

    def test_offline_install_lease_uninstall(self):
        path = self.bundle()
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            self.assertEqual('ready', self.manager.import_zip(path)['state'])
            with self.manager.acquire('media.ffmpeg') as (package, directory):
                self.assertEqual(b'synthetic engine', (directory / package.entries['ffmpeg']).read_bytes())
                self.assert_code('busy', lambda: self.manager.uninstall(package.id))
            self.assertEqual('not_installed', self.manager.uninstall('media.ffmpeg')['state'])

    def test_signature_platform_hash_and_paths(self):
        cases = [
            ('platform_unavailable', lambda p: p.update(platform='windows-x86_64')),
            ('archive_hash_mismatch', lambda p: p.update(sha256='0'*64)),
        ]
        for code, mutate in cases:
            self.assert_code(code, lambda mutate=mutate: self.manager.import_zip(self.bundle(mutate=mutate)))
        self.assert_code('unsafe_path', lambda: self.manager.import_zip(self.bundle(filename='../escape')))
        self.manager.public_keys = (Ed25519PrivateKey.generate().public_key().public_bytes_raw(),)
        self.assert_code('signature_invalid', lambda: self.manager.import_zip(self.bundle()))

    def test_failed_upgrade_preserves_previous(self):
        self.manager.import_zip(self.bundle('2.0.0'))
        self.assert_code('version_rollback', lambda: self.manager.import_zip(self.bundle('1.0.0')))
        self.manager.selfchecks['media.ffmpeg'] = lambda *args: False
        self.assert_code('selfcheck_failed', lambda: self.manager.import_zip(self.bundle('3.0.0')))
        self.assertEqual('2.0.0', self.manager.status('media.ffmpeg')['version'])

    def test_unconfigured_and_missing_adapter(self):
        manager = PackManager(self.directory / 'empty')
        self.assert_code('not_configured', lambda: manager.import_zip(self.bundle()))
        self.assertFalse(manager.root.exists())
        self.manager.selfchecks.clear()
        self.assert_code('engine_check_unavailable', lambda: self.manager.import_zip(self.bundle()))

    def test_symlink_and_extra_members(self):
        path = self.bundle()
        link = self.directory / 'link.zip'
        link.symlink_to(path)
        self.assert_code('invalid_archive', lambda: self.manager.import_zip(link))
        with ZipFile(path, 'a') as archive:
            archive.writestr('install.sh', 'not executed')
        self.assert_code('unsafe_archive', lambda: self.manager.import_zip(path))

    def test_cancel_and_recovery(self):
        def check(directory, package, event):
            self.manager.cancel(package.id)
            return True
        self.manager.selfchecks['media.ffmpeg'] = check
        self.assert_code('cancelled', lambda: self.manager.import_zip(self.bundle()))
        self.manager.recover('media.ffmpeg')
        self.assertFalse((self.manager.root / 'media.ffmpeg' / '.staging').exists())
