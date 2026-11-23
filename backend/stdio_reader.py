"""Bounded control-pipe reads without holding Windows CRT descriptor locks."""
import sys
from contextlib import contextmanager


class PipeReader:
    """One-reader framing over a byte source; never closes the borrowed pipe."""
    def __init__(self, read):
        self.read = read
        self.pending = bytearray()

    def readline(self, limit=2 * 1024 * 1024 + 1):
        if limit <= 0:
            raise ValueError('A positive frame limit is required')
        while True:
            newline = self.pending.find(b'\n', 0, limit)
            if newline >= 0 or len(self.pending) >= limit:
                end = newline + 1 if newline >= 0 else limit
                result = bytes(self.pending[:end])
                del self.pending[:end]
                return result
            data = self.read(min(65536, limit - len(self.pending)))
            if not data:
                result = bytes(self.pending)
                self.pending.clear()
                return result
            self.pending.extend(data)


def native_reader(stream):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    read_file = kernel.ReadFile
    read_file.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    read_file.restype = wintypes.BOOL
    handle = msvcrt.get_osfhandle(stream.fileno())

    def read(size):
        buffer = ctypes.create_string_buffer(size)
        count = wintypes.DWORD()
        if not read_file(handle, buffer, size, ctypes.byref(count), None):
            error = ctypes.get_last_error()
            if error in (38, 109):  # ERROR_HANDLE_EOF / ERROR_BROKEN_PIPE
                return b''
            raise ctypes.WinError(error)
        return buffer.raw[:count.value]

    return PipeReader(read)


@contextmanager
def control_reader(stream):
    # Even a duplicated fd still enters the CRT read path, which can deadlock
    # NumPy/OpenBLAS DLL initialization while it inspects CRT handles. ReadFile
    # releases the GIL without taking those locks; libraries remain lazy-loaded.
    # This handle is borrowed: only the host owns pipe closure and EOF.
    yield native_reader(stream) if sys.platform == 'win32' else stream
