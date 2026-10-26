"""本地桌面运行时基础行为测试。"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch


class LocalPathsTest(TestCase):
    def test_local_paths_live_under_calabash_home_dir(self):
        from core import local_paths

        with TemporaryDirectory() as tmp_dir:
            with patch.object(Path, "home", return_value=Path(tmp_dir)):
                self.assertEqual(local_paths.app_dir(), Path(tmp_dir) / ".calabash")
                self.assertEqual(
                    local_paths.database_path(),
                    Path(tmp_dir) / ".calabash" / "calabash.db",
                )
                self.assertEqual(
                    local_paths.tools_dir(),
                    Path(tmp_dir) / ".calabash" / "tools",
                )


class LocalDatabaseTest(TestCase):
    def test_database_manager_uses_sqlite_path(self):
        from core import database

        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "calabash.db"
            with (
                patch.object(database, "database_path", return_value=db_path),
                patch.object(database, "ensure_local_dirs", return_value=None),
            ):
                manager = database.DatabaseManager()
                try:
                    manager.create_tables()
                    self.assertTrue(db_path.exists())
                finally:
                    manager.close()
