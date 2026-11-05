"""Run-scoped, non-overwriting output files for local tools."""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from threading import Lock
from uuid import uuid4

from core.local_paths import app_dir
from service.files import output_history


class ToolOutputs:
    """Create one output directory per execution; publish only completed files."""

    def __init__(self, *, owner=None):
        self.id = uuid4().hex
        self.owner = owner or (f"session:{self.id}", None)
        self.root = (app_dir() / "outputs").resolve()
        self.directory = self._directory(self.id, self.owner[1])
        self._run_lock = Lock()

    def start_run(self):
        """Start a fresh batch without losing earlier results in this scope."""
        with self._run_lock:
            self.id = uuid4().hex
            self.directory = self._directory(self.id, self.owner[1])

    def _directory(self, run_id, chat_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid output run")
        group = hashlib.sha256(chat_id.encode()).hexdigest() if chat_id is not None else "standalone"
        return self.root / group / run_id

    def write(self, name, writer):
        """Call writer(Path) on a private file, then publish without overwriting.

        Run blocking writers with sdk.io. A failed writer never
        produces a visible result. The suffix is preserved for office libraries.
        """
        if not name or Path(name).name != name or name in {".", ".."} or "\\" in name:
            raise ValueError("Invalid output filename")
        # A writer already in flight keeps its run when the UI starts another.
        with self._run_lock:
            run_id, directory = self.id, self.directory
        output_history.check_owner(self.owner)
        if directory.parent.is_symlink():
            raise ValueError("Invalid output location")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.is_symlink() or directory.parent.is_symlink():
            raise ValueError("Invalid output location")
        target = directory / name
        temporary = directory / f".{uuid4().hex}{target.suffix}"
        published = None
        try:
            writer(temporary)
            if temporary.is_symlink() or not temporary.is_file() or temporary.stat().st_nlink != 1:
                raise ValueError("Output must be a regular file")
            for index in range(10000):
                candidate = target if index == 0 else target.with_name(f"{target.stem} ({index}){target.suffix}")
                try:
                    os.link(temporary, candidate)
                    published = candidate
                    break
                except FileExistsError:
                    continue
            else:
                raise ValueError("Too many output files")
            file_id = uuid4().hex
            output_history.register(run_id, self.owner, file_id, candidate.name, candidate.stat())
            published = None
            return file_id
        finally:
            temporary.unlink(missing_ok=True)
            if published is not None:
                published.unlink(missing_ok=True)

    def path(self, file_id):
        rows = output_history.records(self.owner, file_id=file_id)
        if not rows:
            raise KeyError(file_id)
        return self._record_path(rows[0])

    def _record_path(self, row):
        name = row["name"]
        if not name or Path(name).name != name or name in {".", ".."} or "\\" in name:
            raise ValueError("Invalid output filename")
        directory = self._directory(row["run_id"], row["chat_id"])
        path = directory / name
        info = path.lstat()
        signature = (row["device"], row["inode"], row["size"], row["mtime_ns"])
        if not stat.S_ISREG(info.st_mode) or signature != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
            raise ValueError("Output file has changed or is unavailable")
        if directory.is_symlink() or directory.parent.is_symlink() or path.resolve().parent != directory:
            raise ValueError("Invalid output location")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or signature != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
                raise ValueError("Output file has changed or is unavailable")
        finally:
            os.close(descriptor)
        return path

    def files(self, *, limit=None):
        result = []
        for row in output_history.records(self.owner, limit=limit):
            public = {key: row[key] for key in ("id", "name", "size", "run_id", "created")}
            try:
                self._record_path(row)
                public["available"] = True
            except (OSError, ValueError):
                public["available"] = False
            result.append(public)
        return result

    def save_ticket(self, file_id):
        """Authorize one native save dialog without accepting a UI source path."""
        path = self.path(file_id)
        directory = os.environ.get("CALABASH_SELECTION_DIR")
        if not directory:
            return None
        token = uuid4().hex
        payload = {"path": str(path), "size": path.stat().st_size, "created": time.time()}
        with open(Path(directory) / f"output-{token}.json", "x", encoding="utf-8") as handle:
            os.chmod(handle.name, 0o600)
            json.dump(payload, handle)
        return token

    def open(self, file_id, *, reveal=False):
        path = self.path(file_id)
        if sys.platform == "darwin":
            command = ["open", "-R", str(path)] if reveal else ["open", str(path)]
        elif sys.platform == "win32":
            if not reveal:
                os.startfile(path)
                return
            command = ["explorer", f"/select,{path}"]
        else:
            command = ["xdg-open", str(path.parent if reveal else path)]
        subprocess.run(command, check=True, timeout=10, capture_output=True)
