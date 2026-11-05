import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.chat import ai_chat
from service.files import conversation_files as files
from service.files import file_readers


class FileReaderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        patcher = patch.object(ai_chat, "app_dir", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def attach(self, path):
        item = files.register("one", path)
        history = ai_chat.read_chat("one")
        ai_chat.save_chat("one", [*history, {"role": "user", "content": "read", "attachments": [item["id"]]}])
        return item["id"]

    async def test_excel_structure_and_paginated_rows(self):
        from openpyxl import Workbook
        path = self.root / "office.xlsx"
        workbook = Workbook()
        workbook.active.title = "Sales"
        workbook.active.append(["Team", "Person", "Amount"])
        for number in range(105):
            workbook.active.append(["A", f"P{number}", number])
        workbook.create_sheet("Other")
        workbook.save(path)
        file_id = self.attach(path)
        metadata = await file_readers.read_attachment("one", file_id)
        self.assertEqual(["Sales", "Other"], [sheet["name"] for sheet in metadata["sheets"]])
        result = await file_readers.read_attachment("one", file_id, sheet="Sales", limit=100)
        self.assertEqual(["Team", "Person", "Amount"], result["columns"])
        self.assertEqual(100, len(result["rows"]))
        self.assertTrue(result["truncated"])
        following = await file_readers.read_attachment("one", file_id, sheet="Sales", offset=result["next_offset"])
        self.assertEqual(5, len(following["rows"]))

    async def test_text_csv_limits_and_private_scope(self):
        path = self.root / "note.txt"
        path.write_text("x" * 21000)
        file_id = self.attach(path)
        result = await file_readers.read_attachment("one", file_id)
        self.assertEqual(20000, len(result["text"]))
        self.assertTrue(result["truncated"])
        self.assertEqual("not_found", (await file_readers.read_attachment("two", file_id))["error"]["code"])
        path.write_text("changed")
        self.assertEqual("changed", (await file_readers.read_attachment("one", file_id))["error"]["code"])
        path = self.root / "table.csv"
        path.write_text('\ufeffname,value\n"a,b",2\nc,3\n', encoding="utf-8")
        result = await file_readers.read_attachment("one", self.attach(path), limit=1)
        self.assertEqual([["a,b", "2"]], result["rows"])
        self.assertEqual(1, result["next_offset"])

    async def test_draft_and_deleted_references_are_not_readable(self):
        path = self.root / "draft.txt"
        path.write_text("secret")
        item = files.register("one", path)
        self.assertEqual("not_found", (await file_readers.read_attachment("one", item["id"]))["error"]["code"])
        file_id = self.attach(path)
        ai_chat.delete_chat("one")
        self.assertEqual("not_found", (await file_readers.read_attachment("one", file_id))["error"]["code"])

    async def test_pdf_docx_and_error_codes(self):
        from docx import Document
        from pypdf import PdfWriter
        path = self.root / "office.docx"
        document = Document()
        document.add_paragraph("Office document")
        document.add_table(rows=1, cols=1).cell(0, 0).text = "Table cell"
        document.save(path)
        result = await file_readers.read_attachment("one", self.attach(path))
        self.assertIn("Office document", result["text"])
        self.assertIn("Table cell", result["text"])
        path = self.root / "scan.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(path)
        self.assertEqual("ocr_required", (await file_readers.read_attachment("one", self.attach(path)))["error"]["code"])
        path = self.root / "bad.xlsx"
        path.write_text("invalid")
        self.assertEqual("corrupt", (await file_readers.read_attachment("one", self.attach(path)))["error"]["code"])

    async def test_worker_timeout_is_reaped(self):
        path = self.root / "note.txt"
        path.write_text("test")
        with patch.object(file_readers, "WORKER_TIMEOUT", 0.000001):
            result = await file_readers.read_attachment("one", self.attach(path))
        self.assertEqual("timeout", result["error"]["code"])

    async def test_archive_encoding_and_unsupported_limits(self):
        import zipfile

        from service.files import file_reader_worker as worker
        path = self.root / "large.docx"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", "x" * 1000)
        with path.open("rb") as handle, patch.object(worker, "MAX_EXPANDED", 100), self.assertRaises(ValueError):
            worker.check_archive(handle)
        path = self.root / "bad.txt"
        path.write_bytes(b"\xff\xff")
        self.assertEqual("encoding", (await file_readers.read_attachment("one", self.attach(path)))["error"]["code"])
        path = self.root / "audio.wav"
        path.write_bytes(b"audio")
        self.assertEqual("unsupported", (await file_readers.read_attachment("one", self.attach(path)))["error"]["code"])

    async def test_cancel_kills_and_waits_for_worker(self):
        import asyncio
        from unittest.mock import AsyncMock, Mock
        path = self.root / "wait.txt"
        path.write_text("wait")
        file_id = self.attach(path)
        started = asyncio.Event()

        async def communicate(payload):
            started.set()
            await asyncio.Event().wait()

        process = Mock(returncode=None)
        process.communicate = communicate
        process.wait = AsyncMock(return_value=-9)
        with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)):
            task = asyncio.create_task(file_readers.read_attachment("one", file_id))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()
