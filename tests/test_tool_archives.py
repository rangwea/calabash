import io
import json
import stat
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from sqlmodel import Session, SQLModel, create_engine, select

from models.tool import Tool
from service.tools import (
    tool_activity,
)
from service.tools import (
    tool_archives as archives,
)
from service.tools import (
    tool_manage_service as tools,
)

SOURCE = b'"""\nname: Example\ndescription: Local tool\nrequires: media.ffmpeg>=9.0.2\n"""\nraise AssertionError("must not execute")\ndef main(): pass\n'


class ToolArchiveTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.tools = self.root / "tools"
        self.path = self.tools / "demo/example.py"
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(SOURCE)
        self.engine = create_engine(f"sqlite:///{self.root / 'index.db'}")
        self.addCleanup(self.engine.dispose)
        SQLModel.metadata.create_all(self.engine)
        from core.database import db_manager

        self.stack.enter_context(patch.object(db_manager, "engine", self.engine))
        self.stack.enter_context(
            patch.object(archives, "tools_dir", return_value=self.tools)
        )
        self.stack.enter_context(
            patch.object(tools, "tools_dir", return_value=self.tools)
        )
        self.stack.enter_context(patch.object(tools, "ensure_local_dirs"))
        self.stack.enter_context(patch.object(tool_activity, "_active", {}))

    def write_zip(self, entries=None, manifest=None):
        path = self.root / "tool.zip"
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            if entries is None:
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        manifest
                        or {
                            "format": archives.FORMAT,
                            "version": 1,
                            "project": "demo",
                            "name": "example",
                        }
                    ),
                )
                archive.writestr("tool.py", SOURCE)
            else:
                for name, content in entries:
                    archive.writestr(name, content)
        return path

    def package(self):
        return archives.inspect_zip(self.write_zip())

    def test_export_contains_only_manifest_and_source(self):
        self.path.with_name("example.py.calabash.json").write_text(
            '{"private": "not exported"}'
        )
        self.path.with_name("business.xlsx").write_text("private")
        with ZipFile(io.BytesIO(archives.export_zip("demo", "example"))) as archive:
            self.assertEqual(["manifest.json", "tool.py"], archive.namelist())
            self.assertEqual(SOURCE, archive.read("tool.py"))
            self.assertEqual(
                "demo", json.loads(archive.read("manifest.json"))["project"]
            )

    def test_roundtrip_renaming_indexes_without_executing_source(self):
        exported = self.root / "exported.zip"
        exported.write_bytes(archives.export_zip("demo", "example"))
        package = archives.inspect_zip(exported)
        self.assertEqual("Example", package.title)
        self.assertEqual("media.ffmpeg>=9.0.2", package.requires)
        archives.install(package, "office", "copy")
        self.assertEqual(SOURCE, (self.tools / "office/copy.py").read_bytes())
        with Session(self.engine) as session:
            record = session.exec(select(Tool).where(Tool.project == "office")).one()
            self.assertEqual("copy.py", record.filename)
            self.assertEqual("Example", record.display_name)
        self.assertEqual(SOURCE, self.path.read_bytes())

    def test_conflict_requires_current_revision_and_explicit_overwrite(self):
        package = self.package()
        with self.assertRaises(archives.ToolArchiveError) as error:
            archives.install(package, "demo", "example")
        self.assertEqual("conflict", error.exception.code)
        revision = archives.target_revision("demo", "example")
        self.path.write_bytes(b"def main(): return 1\n")
        with self.assertRaises(archives.ToolArchiveError) as error:
            archives.install(package, "demo", "example", expected_revision=revision)
        self.assertEqual("changed", error.exception.code)
        sidecar = self.path.with_name("example.py.calabash.json")
        sidecar.write_text("{}")
        archives.install(
            package,
            "demo",
            "example",
            expected_revision=archives.target_revision("demo", "example"),
        )
        self.assertEqual(SOURCE, self.path.read_bytes())
        self.assertFalse(sidecar.exists())

    def test_running_tool_cannot_be_overwritten(self):
        tool_activity._active["custom"] = SimpleNamespace(
            owner="custom", tool_owner="tool:demo/example"
        )
        with self.assertRaises(archives.ToolArchiveError) as error:
            archives.install(
                self.package(),
                "demo",
                "example",
                expected_revision=archives.target_revision("demo", "example"),
            )
        self.assertEqual("busy", error.exception.code)
        self.assertEqual(SOURCE, self.path.read_bytes())

    def test_rejects_traversal_extra_files_duplicate_paths_and_plugin_zips(self):
        for entries in [
            [("../escape.py", SOURCE)],
            [("/absolute.py", SOURCE)],
            [("manifest.json", b"{}"), ("tool.py", SOURCE), ("extra.py", SOURCE)],
            [("manifest.json", b"{}"), ("manifest.json", b"{}")],
            [("plugin.json", b"{}"), ("ffmpeg", b"binary")],
        ]:
            with (
                self.subTest(entries=[name for name, _ in entries]),
                self.assertRaises(archives.ToolArchiveError),
            ):
                archives.inspect_zip(self.write_zip(entries))
        self.assertFalse((self.root / "escape.py").exists())

    def test_rejects_symlink_zip_entry_and_unsupported_manifest(self):
        link = ZipInfo("tool.py")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(archives.ToolArchiveError):
            archives.inspect_zip(
                self.write_zip([("manifest.json", b"{}"), (link, b"/private/file")])
            )
        for manifest in [
            {"format": "plugin", "version": 1},
            {"format": archives.FORMAT, "version": 2},
            {"format": archives.FORMAT, "version": True},
            {
                "format": archives.FORMAT,
                "version": 1,
                "project": "..",
                "name": "outside",
            },
        ]:
            with (
                self.subTest(manifest=manifest),
                self.assertRaises(archives.ToolArchiveError),
            ):
                archives.inspect_zip(self.write_zip(manifest=manifest))

    def test_rejects_oversized_zip_manifest_source_and_invalid_code(self):
        path = self.root / "large.zip"
        path.write_bytes(b"x" * (archives.MAX_ARCHIVE + 1))
        with self.assertRaises(archives.ToolArchiveError):
            archives.inspect_zip(path)
        for content in [b"invalid", b"def main(:", b"print('missing main')", b"\xff"]:
            manifest = json.dumps(
                {
                    "format": archives.FORMAT,
                    "version": 1,
                    "project": "demo",
                    "name": "x",
                }
            )
            with self.assertRaises(archives.ToolArchiveError):
                archives.inspect_zip(
                    self.write_zip([("manifest.json", manifest), ("tool.py", content)])
                )
        with (
            patch.object(archives, "MAX_SOURCE", 10),
            self.assertRaises(archives.ToolArchiveError),
        ):
            archives.inspect_zip(self.write_zip())
        with (
            patch.object(archives, "MAX_MANIFEST", 10),
            self.assertRaises(archives.ToolArchiveError),
        ):
            archives.inspect_zip(self.write_zip())

    def test_target_symlinks_and_invalid_names_are_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.tools / "linked").symlink_to(outside, target_is_directory=True)
        for project, name in [
            ("../outside", "x"),
            ("demo", "../x"),
            ("linked", "x"),
            ("demo", "__init__"),
            ("_hidden", "x"),
        ]:
            with (
                self.subTest(project=project, name=name),
                self.assertRaises(archives.ToolArchiveError),
            ):
                archives.install(self.package(), project, name)
        self.assertFalse(list(outside.iterdir()))

    def test_failed_write_keeps_existing_source(self):
        revision = archives.target_revision("demo", "example")
        with (
            patch.object(Path, "replace", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            archives.install(
                self.package(), "demo", "example", expected_revision=revision
            )
        self.assertEqual(SOURCE, self.path.read_bytes())
        self.assertFalse(list(self.path.parent.glob(".*.tmp")))

    def test_delivery_ticket_is_private_short_lived_and_contains_only_zip(self):
        tickets = self.root / "tickets"
        tickets.mkdir()
        with patch.dict("os.environ", {"CALABASH_SELECTION_DIR": str(tickets)}):
            with archives.export_delivery("demo", "example") as (data, token):
                ticket = tickets / f"output-{token}.json"
                payload = json.loads(ticket.read_text())
                temporary = Path(payload["path"])
                self.assertEqual(data, temporary.read_bytes())
                self.assertEqual("example.zip", temporary.name)
                self.assertEqual(0o600, stat.S_IMODE(ticket.stat().st_mode))
            self.assertFalse(ticket.exists())
            self.assertFalse(temporary.exists())
