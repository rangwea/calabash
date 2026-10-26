import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from nicegui import core, ui

from component import tool_files
from service.chat import ai_chat
from service.files import conversation_files
from service.files import tool_inputs
from service.files.tool_input_selection import ToolInputSelection


class SelectionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.first = self.root / "first.csv"
        self.second = self.root / "second.csv"
        self.first.write_text("one")
        self.second.write_text("two")
        patcher = patch.object(ai_chat, "app_dir", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_append_deduplicates_aliases_and_remove_clear_never_delete_files(self):
        selection = ToolInputSelection([])
        alias = self.root / "alias.csv"
        alias.symlink_to(self.first)
        hardlink = self.root / "hardlink.csv"
        hardlink.hardlink_to(self.first)
        self.assertEqual(1, selection.add([self.first, self.first, alias, hardlink]))
        self.assertEqual(1, selection.add([self.second]))
        first = selection.files()[0]
        self.assertEqual("CSV", first["type"])
        self.assertEqual(3, first["size"])
        self.assertEqual("ready", first["status"])
        self.assertTrue(selection.remove(first["key"]))
        self.assertEqual([str(self.second)], selection.paths())
        self.assertFalse(selection.remove(first["key"]))
        self.assertTrue(selection.clear())
        self.assertEqual([], selection.paths())
        self.assertEqual("one", self.first.read_text())
        self.assertEqual("two", self.second.read_text())

    def test_missing_changed_and_denied_files_require_explicit_reselect(self):
        selection = ToolInputSelection([])
        selection.add([self.first, self.second])
        first, second = selection.files()
        self.first.write_text("changed")
        self.second.unlink()
        self.assertEqual(["changed", "missing"], [row["status"] for row in selection.files()])
        with self.assertRaises(ValueError):
            selection.paths()
        self.assertTrue(selection.replace(first["key"], self.first))
        self.assertEqual("ready", selection.files()[0]["status"])
        with patch("service.files.tool_input_selection.os.open", side_effect=PermissionError):
            self.assertEqual("denied", selection.files()[0]["status"])
        self.assertTrue(selection.remove(second["key"]))
        self.assertEqual([str(self.first)], selection.paths())

    def test_snapshot_is_immutable_and_all_mutations_are_blocked_while_locked(self):
        selection = ToolInputSelection([])
        selection.add([self.first])
        key = selection.files()[0]["key"]
        snapshot = selection.freeze()
        self.assertEqual((str(self.first),), snapshot)
        self.assertEqual(0, selection.add([self.second]))
        self.assertFalse(selection.remove(key))
        self.assertFalse(selection.clear())
        self.assertFalse(selection.replace(key, self.second))
        selection.set_locked(False)
        selection.clear()
        selection.add([self.second])
        self.assertEqual((str(self.first),), snapshot)
        self.assertEqual([str(self.second)], selection.paths())

    def test_symlink_retarget_and_directory_are_not_usable_inputs(self):
        alias = self.root / "alias.csv"
        alias.symlink_to(self.first)
        selection = ToolInputSelection([])
        selection.add([alias, self.root])
        alias.unlink()
        alias.symlink_to(self.second)
        self.assertEqual(["changed", "not_file"], [row["status"] for row in selection.files()])
        with self.assertRaises(ValueError):
            selection.freeze()
        self.assertFalse(selection.locked)

    @unittest.skipUnless(os.name == "posix" and os.geteuid() != 0, "Requires POSIX file permissions")
    def test_real_file_permission_denial_and_explicit_reselect_recover(self):
        selection = ToolInputSelection([])
        selection.add([self.first])
        key = selection.files()[0]["key"]
        try:
            self.first.chmod(0)
            self.assertEqual("denied", selection.files()[0]["status"])
            with self.assertRaises(ValueError):
                selection.freeze()
            self.assertFalse(selection.locked)
        finally:
            self.first.chmod(0o600)
        self.assertTrue(selection.replace(key, self.first))
        self.assertEqual([str(self.first)], selection.paths())

    def test_reselecting_attachment_does_not_rewrite_sent_reference(self):
        item = conversation_files.register("one", self.first)
        messages = [{"role": "user", "content": "test", "attachments": [item["id"]]}]
        ai_chat.save_chat("one", messages)
        token = tool_inputs.create("one", "preview", messages)
        selection = ToolInputSelection(tool_inputs.resolve(token, "preview"), context=(token, "preview"))
        key = selection.files()[0]["key"]
        self.first.write_text("changed attachment")
        self.assertEqual("changed", selection.files()[0]["status"])
        selection.replace(key, self.first)
        self.assertEqual("ready", selection.files()[0]["status"])
        self.assertEqual("changed", conversation_files.check("one", item["id"]))
        ai_chat.delete_chat("one")
        self.assertEqual([str(self.first)], selection.paths())
        self.assertTrue(self.first.exists())

    def test_expired_context_blocks_only_remaining_attachment_references(self):
        item = conversation_files.register("one", self.first)
        messages = [{"role": "user", "content": "test", "attachments": [item["id"]]}]
        ai_chat.save_chat("one", messages)
        token = tool_inputs.create("one", "preview", messages)
        selection = ToolInputSelection(tool_inputs.resolve(token, "preview"), context=(token, "preview"))
        key = selection.files()[0]["key"]
        selection.add([self.second])
        ai_chat.delete_chat("one")
        self.assertEqual(["expired", "ready"], [row["status"] for row in selection.files()])
        selection.remove(key)
        self.assertEqual([str(self.second)], selection.paths())


class SelectionUITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.container = ui.column()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.first = self.root / "first.csv"
        self.second = self.root / "second.csv"
        self.first.write_text("one")
        self.second.write_text("two")

    async def test_cancel_and_late_picker_result_cannot_change_frozen_batch(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def choose():
            entered.set()
            await release.wait()
            return [str(self.second)]

        with patch.object(core, "loop", asyncio.get_running_loop()), self.container, patch.object(tool_inputs, "current_inputs", return_value=[]):
            selector = tool_files.ToolFileInput()
            selector.add_paths([self.first])
            with patch.object(tool_files, "choose_paths", AsyncMock(return_value=[])):
                await selector.add_files()
            self.assertEqual([str(self.first)], selector.paths)
            with patch.object(tool_files, "choose_paths", choose):
                pending = asyncio.create_task(selector.add_files())
                await entered.wait()
                snapshot = selector.freeze()
                selector.unfreeze()
                release.set()
                await pending
            self.assertEqual((str(self.first),), snapshot)
            self.assertEqual([str(self.first)], selector.paths)
            selector.freeze()
            with patch.object(tool_files, "choose_paths", AsyncMock()) as picker:
                await selector.add_files()
                picker.assert_not_awaited()
            selector.clear()
            self.assertEqual([str(self.first)], selector.paths)
            selector.unfreeze()
            selector.clear()
            self.assertEqual([], selector.paths)
