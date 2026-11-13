"""Tool-owned SQLite connections and short, explicit transactions."""

import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from threading import Lock

from core.local_paths import app_dir


class ToolDatabase:
    def __init__(self, directory):
        self.directory = directory
        self.path = directory / 'data.sqlite'
        self._ready = False
        self._lock = Lock()
        self._check_directory()

    def _check_directory(self):
        root = app_dir()
        relative = self.directory.relative_to(root)
        current = root
        for part in (None, *relative.parts):
            if part is not None:
                current = current / part
            if current.is_symlink():
                raise ValueError('Linked tool data is forbidden')
            current.mkdir(exist_ok=True, parents=part is None, mode=0o700)

    def _connect(self):
        self._check_directory()
        for suffix in ('', '-journal', '-wal', '-shm'):
            path = self.path.with_name(self.path.name + suffix)
            if path.is_symlink():
                raise ValueError('Linked tool database is forbidden')
            if path.exists():
                info = path.stat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError('Tool database must be a private regular file')
        db = sqlite3.connect(self.path, timeout=15, autocommit=True)
        try:
            if os.name != 'nt':
                self.path.chmod(0o600)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys = ON')
            return db
        except BaseException:
            db.close()
            raise

    @contextmanager
    def transaction(self, *, write=False):
        if type(write) is not bool:
            raise ValueError('write must be a boolean')
        if not self._ready:
            with self._lock:
                if not self._ready:
                    db = self._connect()
                    try:
                        db.execute('BEGIN IMMEDIATE')
                        db.execute('CREATE TABLE IF NOT EXISTS _calabash_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                        db.execute('COMMIT')
                        self._ready = True
                    finally:
                        db.close()
        db = self._connect()
        try:
            if not write:
                db.execute('PRAGMA query_only = ON')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
        finally:
            db.close()

    @staticmethod
    def _setting_key(key):
        if not isinstance(key, str) or not key or len(key) > 200 or any(ord(char) < 32 for char in key):
            raise ValueError('Invalid setting key')
        return key

    def get_setting(self, key, default=None):
        key = self._setting_key(key)
        with self.transaction() as db:
            row = db.execute('SELECT value FROM _calabash_settings WHERE key = ?', (key,)).fetchone()
            return json.loads(row['value']) if row is not None else default

    def set_setting(self, key, value):
        key = self._setting_key(key)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        with self.transaction(write=True) as db:
            db.execute('INSERT INTO _calabash_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, encoded))
