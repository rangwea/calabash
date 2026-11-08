"""Validate a host-selected regular file without reading its contents."""
import os
import stat
from pathlib import Path


def snapshot(path):
    original = Path(os.path.abspath(path))
    resolved = original.resolve(strict=True)
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("not_file")
    # Open without reading content to check actual backend access, not mode bits.
    fd = os.open(resolved, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("changed")
    finally:
        os.close(fd)
    return original, resolved, info
