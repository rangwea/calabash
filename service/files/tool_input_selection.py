"""Draft file references, independent of immutable conversation attachments."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from service.files import conversation_files
from service.files import tool_inputs


def _observe(path):
    try:
        resolved = path.resolve(strict=True)
        before = resolved.stat()
        if not stat.S_ISREG(before.st_mode):
            return "not_file", None
        descriptor = os.open(resolved, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        try:
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        def signature(value):
            return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        if signature(before) != signature(after):
            return "changed", None
        return "ready", (os.path.normcase(str(resolved)), *signature(after))
    except PermissionError:
        return "denied", None
    except (OSError, ValueError, RuntimeError):
        return "missing", None


@dataclass(frozen=True)
class _Entry:
    key: str
    path: Path
    name: str
    signature: tuple | None
    size: int | None
    reference: tuple | None


class ToolInputSelection:
    def __init__(self, records, context=None):
        self.context = context
        self.locked = False
        self.revision = 0
        self._entries = []
        for record in records:
            entry = self._entry(record["path"], record)
            if not any(self._same(entry, old) for old in self._entries):
                self._entries.append(entry)

    def __len__(self):
        return len(self._entries)

    def _entry(self, path, record=None, key=None):
        record = record or {}
        path = Path(path).expanduser().absolute()
        _, signature = _observe(path)
        reference = (record.get("chat_id", ""), record["id"]) if record.get("id") else None
        return _Entry(key or uuid4().hex, path, record.get("name") or path.name, signature, record.get("size", signature[3] if signature else None), reference)

    @staticmethod
    def _same(left, right):
        if os.path.normcase(str(left.path)) == os.path.normcase(str(right.path)):
            return True
        a, b = left.signature, right.signature
        return bool(a and b and (a[0] == b[0] or (a[2] and a[1:3] == b[1:3])))

    def add(self, paths):
        if self.locked:
            return 0
        count = 0
        for path in paths:
            entry = self._entry(path)
            if not any(self._same(entry, old) for old in self._entries):
                self._entries.append(entry)
                count += 1
        if count:
            self.revision += 1
        return count

    def remove(self, key):
        if self.locked:
            return False
        for entry in self._entries:
            if entry.key == key:
                self._entries.remove(entry)
                self.revision += 1
                return True
        return False

    def clear(self):
        if self.locked or not self._entries:
            return False
        self._entries.clear()
        self.revision += 1
        return True

    def replace(self, key, path):
        if self.locked:
            return False
        entry = self._entry(path, key=key)
        if any(old.key != key and self._same(entry, old) for old in self._entries):
            return False
        for index, old in enumerate(self._entries):
            if old.key == key:
                self._entries[index] = entry
                self.revision += 1
                return True
        return False

    def files(self):
        valid = True
        if self.context and any(entry.reference for entry in self._entries):
            try:
                tool_inputs.owner(*self.context)
            except ValueError:
                valid = False
        rows = []
        for entry in self._entries:
            status, signature = _observe(entry.path)
            if entry.reference:
                reference_status = conversation_files.check(*entry.reference) if valid else "expired"
                if reference_status != "ready":
                    status = reference_status
            if status == "ready" and signature != entry.signature:
                status = "changed"
            rows.append({"key": entry.key, "name": entry.name, "type": entry.path.suffix.lstrip(".").upper(), "size": entry.size, "status": status})
        return rows

    def paths(self):
        if any(row["status"] != "ready" for row in self.files()):
            raise ValueError("files_unavailable")
        return [str(entry.path) for entry in self._entries]

    def set_locked(self, locked):
        if self.locked != locked:
            self.locked = locked
            self.revision += 1

    def freeze(self):
        snapshot = tuple(self.paths())
        self.set_locked(True)
        return snapshot
