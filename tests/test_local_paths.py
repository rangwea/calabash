"""Local data roots hold tool source, results and databases; only the user may read them."""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import local_paths


class LocalPathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        patcher = patch('core.local_paths.Path.home', return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    @unittest.skipIf(os.name == 'nt', 'Windows does not model POSIX directory bits')
    def test_created_roots_are_private_to_the_user(self):
        local_paths.ensure_local_dirs()
        for path in (local_paths.app_dir(), local_paths.tools_dir(), local_paths.logs_dir()):
            self.assertTrue(path.is_dir(), path)
            self.assertEqual(0o700, self.mode(path), f'{path} must not be group/world readable')

    @unittest.skipIf(os.name == 'nt', 'Windows does not model POSIX directory bits')
    def test_permissive_existing_roots_are_tightened(self):
        """A root created by an older build must not stay world readable."""
        local_paths.app_dir().mkdir(parents=True)
        local_paths.tools_dir().mkdir()
        local_paths.app_dir().chmod(0o755)
        local_paths.tools_dir().chmod(0o755)
        local_paths.ensure_local_dirs()
        self.assertEqual(0o700, self.mode(local_paths.app_dir()))
        self.assertEqual(0o700, self.mode(local_paths.tools_dir()))

    def test_roots_stay_under_the_user_home(self):
        self.assertEqual(self.home / '.calabash', local_paths.app_dir())
        self.assertEqual(self.home / '.calabash' / 'tools', local_paths.tools_dir())
        self.assertEqual(self.home / '.calabash' / 'logs', local_paths.logs_dir())
