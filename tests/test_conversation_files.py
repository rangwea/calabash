import asyncio
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from service.chat import ai_chat
from service.files import conversation_files as files


class ConversationFilesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.patch = patch.object(ai_chat, "app_dir", return_value=self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.source = self.root / "sample.txt"
        self.source.write_text("private content")

    def test_drafts_bind_and_history_survives_remove(self):
        attachment = files.register("one", self.source)
        self.assertEqual(attachment["id"], files.register("one", self.source)["id"])
        self.assertEqual(1, len(files.list_files("one", pending=True)))
        messages = [{"role": "user", "content": "process", "id": "message", "attachments": [attachment["id"]]}]
        ai_chat.save_chat("one", messages)
        self.assertEqual([], files.list_files("one", pending=True))
        self.assertFalse(files.remove_pending("one", attachment["id"]))
        self.assertEqual(1, len(files.for_message("one", "message")))
        self.assertNotIn("path", files.for_message("one", "message")[0])
        self.assertEqual(messages, ai_chat.read_chat("one"))

    def test_cross_chat_and_deleted_chat_are_rejected(self):
        attachment = files.register("one", self.source)
        with self.assertRaises(ValueError):
            ai_chat.save_chat("two", [{"role": "user", "content": "no", "attachments": [attachment["id"]]}])
        ai_chat.delete_chat("one")
        with self.assertRaises(ValueError):
            files.register("one", self.source)
        ai_chat.save_chat("one", [{"role": "user", "content": "late"}])
        self.assertEqual([], files.list_files("one"))
        self.assertTrue(self.source.exists())

    def test_changes_missing_and_symlink_retarget(self):
        link = self.root / "link.txt"
        link.symlink_to(self.source)
        attachment = files.register("one", link)
        self.assertEqual("ready", files.check("one", attachment["id"]))
        other = self.root / "other.txt"
        other.write_text("other")
        link.unlink()
        link.symlink_to(other)
        self.assertEqual("changed", files.check("one", attachment["id"]))
        attachment = files.register("one", self.source)
        self.source.write_text("changed")
        self.assertEqual("changed", files.check("one", attachment["id"]))
        self.source.unlink()
        self.assertEqual("missing", files.check("one", attachment["id"]))

    def test_limits_and_special_files(self):
        with self.assertRaises(ValueError):
            files.register("one", self.root)
        fifo = self.root / "pipe"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            files.register("one", fifo)
        for index in range(20):
            path = self.root / f"{index}.txt"
            path.touch()
            files.register("one", path)
        with self.assertRaises(ValueError):
            files.register("one", self.source)

    def test_ticket_single_use_and_no_arbitrary_path(self):
        import json
        import time
        tickets = self.root / "tickets"
        tickets.mkdir()
        token = "a" * 32
        (tickets / f"{token}.json").write_text(json.dumps({"paths": [str(self.source)], "created": time.time()}))
        with patch.dict(os.environ, {"CALABASH_SELECTION_DIR": str(tickets)}):
            self.assertEqual(1, len(files.consume_selection("one", token)))
            with self.assertRaises(ValueError):
                files.consume_selection("one", token)
            with self.assertRaises(ValueError):
                files.consume_selection("one", "../sample")

    def test_upload_limit_and_cleanup(self):
        from nicegui.elements.upload_files import SmallFileUpload
        with patch.object(files, "UPLOAD_LIMIT", 10):
            upload = SmallFileUpload("../../safe.txt", "text/plain", b"ok")
            item = asyncio.run(files.store_upload("one", upload))
            self.assertEqual("safe.txt", item["name"])
            path = Path(files.get_record("one", item["id"])["path"])
            self.assertTrue(path.is_file())
            files.remove_pending("one", item["id"])
            files.cleanup_uploads(now=path.stat().st_mtime + 86401)
            self.assertFalse(path.exists())
            with self.assertRaises(ValueError):
                asyncio.run(files.store_upload("one", SmallFileUpload("big", "", b"x" * 11)))

    def test_provider_request_does_not_send_internal_fields(self):
        from service.chat.model_providers import request
        _, _, payload = request("deepseek", "model", {"base_url": "https://example.test", "key": "key"},
                                [{"role": "user", "content": "hello", "id": "private", "attachments": ["secret"]}], [])
        self.assertEqual([{"role": "user", "content": "hello"}], payload["messages"])


    def test_failed_cross_chat_save_rolls_back(self):
        item = files.register("one", self.source)
        second = files.register("two", self.source)
        with self.assertRaises(ValueError):
            ai_chat.save_chat("two", [{"role": "user", "content": "invalid", "id": "bad", "attachments": [second["id"], item["id"]]}])
        self.assertEqual([], files.for_message("two", "bad"))
        self.assertEqual(1, len(files.list_files("two", pending=True)))

    def test_bound_file_cannot_be_rebound_to_another_message(self):
        item = files.register("one", self.source)
        ai_chat.save_chat("one", [{"role": "user", "content": "first", "id": "first", "attachments": [item["id"]]}])
        with self.assertRaises(ValueError):
            ai_chat.save_chat("one", [{"role": "user", "content": "second", "id": "second", "attachments": [item["id"]]}])
        with self.assertRaises(ValueError):
            ai_chat.save_chat("one", [{"role": "user", "content": "first", "id": "first", "attachments": []}])

    def test_upload_cancel_removes_partial_file(self):
        class CancelledUpload:
            name = "file.txt"

            def size(self):
                return 2

            async def iterate(self):
                yield b"a"
                raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(files.store_upload("one", CancelledUpload()))
        self.assertEqual([], list(files.upload_dir().iterdir()))

    def test_cleanup_keeps_referenced_upload(self):
        from nicegui.elements.upload_files import SmallFileUpload
        item = asyncio.run(files.store_upload("one", SmallFileUpload("file.txt", "", b"ok")))
        path = Path(files.get_record("one", item["id"])["path"])
        files.cleanup_uploads(now=path.stat().st_mtime + 86401)
        self.assertTrue(path.exists())

    def test_concurrent_registration_cannot_exceed_limit(self):
        from concurrent.futures import ThreadPoolExecutor
        paths = []
        for index in range(25):
            path = self.root / f"concurrent-{index}.txt"
            path.touch()
            paths.append(path)

        def attach(path):
            try:
                files.register("one", path)
                return True
            except ValueError as error:
                self.assertEqual("limit", str(error))
                return False

        with ThreadPoolExecutor(max_workers=5) as executor:
            self.assertEqual(20, sum(executor.map(attach, paths)))
        self.assertEqual(20, len(files.list_files("one", pending=True)))
