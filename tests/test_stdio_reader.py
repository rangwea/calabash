"""Transport ownership and framing; no user files or real model calls."""
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.stdio_reader import PipeReader, control_reader, native_reader


class ControlReaderTests(unittest.TestCase):
    def test_non_windows_keeps_supplied_stream_open(self):
        with tempfile.TemporaryFile() as original, patch('backend.stdio_reader.sys.platform', 'darwin'):
            with control_reader(original) as reader:
                self.assertIs(reader, original)
            self.assertFalse(original.closed)

    def test_windows_selects_native_reader_without_closing_input(self):
        with tempfile.TemporaryFile() as original, patch('backend.stdio_reader.sys.platform', 'win32'), patch('backend.stdio_reader.native_reader') as native:
            with control_reader(original) as reader:
                self.assertIs(reader, native.return_value)
                native.assert_called_once_with(original)
            self.assertFalse(original.closed)

    def test_chunked_frames_limits_and_partial_eof(self):
        chunks = iter([b'first\nsec', b'ond\npartial', b''])
        reader = PipeReader(lambda size: next(chunks))
        self.assertEqual(reader.readline(20), b'first\n')
        self.assertEqual(reader.readline(20), b'second\n')
        self.assertEqual(reader.readline(20), b'partial')
        # A persistent byte source returns EOF repeatedly.
        reader.read = lambda size: b''
        self.assertEqual(reader.readline(20), b'')
        reader = PipeReader(lambda size: b'x' * size)
        self.assertEqual(reader.readline(5), b'xxxxx')
        self.assertEqual(len(reader.pending), 0)
        with self.assertRaises(ValueError):
            reader.readline(0)

    def test_native_read_waits_for_available_bytes_and_handles_disconnect(self):
        class Function:
            def __init__(self, call):
                self.call = call

            def __call__(self, *args):
                return self.call(*args)

        counts = iter([0, 0, 3, None])
        pauses, sizes = [], []

        def peek(handle, buffer, size, read, available, left):
            count = next(counts)
            if count is None:
                return False
            available._obj.value = count
            return True

        def read(handle, buffer, size, count, overlapped):
            sizes.append(size)
            buffer.raw = b'a\nb'
            count._obj.value = 3
            return True

        kernel = SimpleNamespace(PeekNamedPipe=Function(peek), ReadFile=Function(read))
        with tempfile.TemporaryFile() as stream, patch.dict(sys.modules, {'msvcrt': SimpleNamespace(get_osfhandle=lambda fd: fd)}), patch('ctypes.WinDLL', return_value=kernel, create=True), patch('ctypes.get_last_error', return_value=109, create=True), patch('backend.stdio_reader.time.sleep', side_effect=pauses.append):
            reader = native_reader(stream)
            self.assertEqual(reader.readline(10), b'a\n')
            self.assertEqual(reader.readline(10), b'b')
        self.assertEqual(sizes, [3])
        self.assertEqual(pauses, [.01, .01])

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows pipe')
    def test_private_pipe_handles_split_frames_and_eof(self):
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd, 'rb') as original:
            def write():
                with os.fdopen(write_fd, 'wb', buffering=0) as writer:
                    writer.write(b'{"id":')
                    writer.write(b'"synthetic"}\n')
            thread = threading.Thread(target=write)
            thread.start()
            try:
                with control_reader(original) as reader:
                    self.assertEqual(reader.readline(100), b'{"id":"synthetic"}\n')
                    self.assertEqual(reader.readline(100), b'')
            finally:
                thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    @unittest.skipUnless(sys.platform == 'win32', 'Windows CRT/native DLL regression')
    def test_cold_office_import_while_control_pipe_waits(self):
        code = """
import sys, threading, faulthandler, time
from backend.stdio_reader import control_reader
faulthandler.dump_traceback_later(20)
ready = threading.Event()
with control_reader(sys.stdin.buffer) as reader:
    def consume():
        reader.readline()
        ready.set()
        reader.readline()
    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    ready.wait()
    time.sleep(.1)
    from openpyxl import Workbook
    from docx import Document
    print('office-imported', flush=True)
    thread.join()
faulthandler.cancel_dump_traceback_later()
"""
        with tempfile.TemporaryFile(mode='w+') as errors:
            process = subprocess.Popen([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True)
            output = queue.Queue()
            reader = threading.Thread(target=lambda: output.put(process.stdout.readline()), daemon=True)
            reader.start()
            try:
                process.stdin.write('start\n')
                process.stdin.flush()
                try:
                    value = output.get(timeout=30)
                except queue.Empty:
                    errors.seek(0)
                    self.fail('Cold office import blocked:\n' + errors.read())
                self.assertEqual(value.strip(), 'office-imported')
            finally:
                process.stdin.close()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    # Synthetic child imports only; it never writes user files.
                    process.kill()
                    process.wait(timeout=5)
                reader.join(timeout=2)
                process.stdout.close()
            errors.seek(0)
            self.assertEqual(process.returncode, 0, errors.read())
