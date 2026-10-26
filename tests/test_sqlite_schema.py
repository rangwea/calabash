import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import inspect
from sqlmodel import SQLModel

import models  # noqa: F401
from core.database import DatabaseManager


class SQLiteSchemaTests(unittest.TestCase):
    def test_create_tables_is_complete_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "calabash.db"
            with (
                patch("core.database.database_path", return_value=path),
                patch("core.database.ensure_local_dirs"),
            ):
                manager = DatabaseManager()
            try:
                manager.create_tables()
                manager.create_tables()
                self.assertEqual(manager.engine.dialect.name, "sqlite")
                self.assertEqual({"tools"}, set(SQLModel.metadata.tables))
                self.assertEqual(
                    set(SQLModel.metadata.tables),
                    set(inspect(manager.engine).get_table_names()),
                )
                self.assertTrue(manager.test_connection())
                self.assertTrue(path.is_file())
            finally:
                manager.close()
