"""First-run startup must not write inside the application installation."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DesktopFirstRunTests(unittest.TestCase):
    def test_logging_uses_user_home_with_read_only_installation_directory(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            home = directory / "new-user"
            install = directory / "readonly-install"
            home.mkdir()
            install.mkdir()
            install.chmod(0o555)
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "from core.logger import LOG_BASE_DIR, logger; from core.local_paths import logs_dir; assert LOG_BASE_DIR == logs_dir(); logger.info('isolated first-run check')",
                    ],
                    cwd=install,
                    env={
                        **os.environ,
                        "HOME": str(home),
                        "USERPROFILE": str(home),
                        "PYTHONPATH": str(root),
                    },
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue((home / ".calabash/logs/app.log").is_file())
                self.assertFalse((install / "logs").exists())
                self.assertIn(
                    "isolated first-run check",
                    (home / ".calabash/logs/app.log").read_text(),
                )
            finally:
                install.chmod(0o755)
