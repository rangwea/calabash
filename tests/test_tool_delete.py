import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nicegui import ui
from sqlmodel import Session, SQLModel, create_engine, select

from models.tool import Tool
from service.tools import tool_activity, tool_manage_service as tools
from ui.tool_list import _confirm_delete_tool


class ToolDeleteTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.path = self.root / "tools/demo/example.py"
        self.path.parent.mkdir(parents=True)
        self.path.write_text("def main(): pass\n")
        self.sidecar = self.path.with_name("example.py.calabash.json")
        self.sidecar.write_text("{}")
        self.revision = tools.calculate_revision(self.path.read_text())
        self.engine = create_engine(f"sqlite:///{self.root / 'index.db'}")
        self.addCleanup(self.engine.dispose)
        SQLModel.metadata.create_all(self.engine)
        from core.database import db_manager

        self.stack.enter_context(patch.object(db_manager, "engine", self.engine))
        self.stack.enter_context(
            patch.object(tools, "tools_dir", return_value=self.root / "tools")
        )
        self.stack.enter_context(patch.object(tools, "app_dir", return_value=self.root))
        self.stack.enter_context(patch.object(tool_activity, "_active", {}))
        with Session(self.engine) as session:
            session.add(Tool(project="demo", filename="example.py"))
            session.add(Tool(project="demo", filename="other.py"))
            session.commit()

    def delete(self):
        tools.delete_tool("demo", "example", revision=self.revision)

    def test_deletes_only_selected_tool_metadata_index_and_recent_record(self):
        recent = self.root / "recent_tools.json"
        recent.write_text(json.dumps(["demo/example", "demo/other"]))
        protected = [
            self.root / name for name in ["chat.db", "results.xlsx", "tool.log"]
        ]
        for path in protected:
            path.write_text("keep")
        self.delete()
        self.assertFalse(self.path.exists())
        self.assertFalse(self.sidecar.exists())
        self.assertEqual(["demo/other"], json.loads(recent.read_text()))
        with Session(self.engine) as session:
            self.assertEqual(
                ["other.py"], [row.filename for row in session.exec(select(Tool)).all()]
            )
        self.assertTrue(all(path.read_text() == "keep" for path in protected))
        self.delete()  # Retry after deletion is harmless.

    def test_running_tool_is_protected_even_with_custom_job_owner(self):
        tool_activity._active["custom"] = SimpleNamespace(
            owner="custom", tool_owner="tool:demo/example"
        )
        with self.assertRaises(tool_activity.ToolBusyError):
            self.delete()
        self.assertTrue(self.path.exists())
        self.assertTrue(self.sidecar.exists())

    def test_other_tool_running_does_not_block_deletion(self):
        tool_activity._active["other"] = SimpleNamespace(owner="tool:demo/other")
        self.delete()
        self.assertFalse(self.path.exists())

    def test_changed_tool_is_not_deleted(self):
        self.path.write_text("def main(): return 1\n")
        with self.assertRaises(ValueError):
            self.delete()
        self.assertTrue(self.path.exists())
        self.assertTrue(self.sidecar.exists())

    def test_rejects_path_traversal_and_symlinks(self):
        with self.assertRaises(ValueError):
            tools.delete_tool("..", "example", revision=self.revision)
        outside = self.root / "outside.py"
        outside.write_text(self.path.read_text())
        self.path.unlink()
        self.path.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.delete()
        self.assertTrue(outside.exists())

    def test_confirmation_requires_explicit_click_and_shows_no_file_path(self):
        with (
            patch("ui.tool_list.delete_tool") as remove,
            patch("ui.tool_list.ui.notify"),
        ):
            existing = set(ui.context.client.elements)
            _confirm_delete_tool(
                {
                    "project": "demo",
                    "name": "example",
                    "title": "Example",
                    "revision": self.revision,
                    "path": "/private/business/example.py",
                },
                lambda: None,
            )
            dialog = next(
                element
                for element in ui.context.client.elements.values()
                if isinstance(element, ui.dialog) and element.id not in existing
            )
            try:
                remove.assert_not_called()
                labels = [
                    element.text
                    for element in dialog.descendants()
                    if isinstance(element, ui.label)
                ]
                self.assertTrue(any("Example" in label for label in labels))
                self.assertFalse(any("/private/" in label for label in labels))
                confirm = next(
                    element
                    for element in dialog.descendants()
                    if isinstance(element, ui.button)
                    and element._props.get("color") == "negative"
                )
                next(iter(confirm._event_listeners.values())).handler(None)
                remove.assert_called_once_with(
                    "demo", "example", revision=self.revision
                )
            finally:
                dialog.delete()
