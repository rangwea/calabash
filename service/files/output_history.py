"""SQLite metadata for tool-owned result files; never deletes file contents."""

import os
import sqlite3
import time
from contextlib import closing, contextmanager

from core.local_paths import app_dir


@contextmanager
def database(*, write=True):
    """Writers serialize on BEGIN IMMEDIATE; readers never block them.

    Result listings run while batches write, so a reader must not take the
    database-wide write lock just to list history.
    """
    root = app_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "tool-results.sqlite"
    if path.is_symlink():
        raise ValueError("Linked result database is forbidden")
    with closing(sqlite3.connect(path, timeout=15)) as db, db:
        if os.name != "nt":
            path.chmod(0o600)
        # WAL keeps the readers below from starving the writer and vice versa.
        db.execute("PRAGMA journal_mode=WAL")
        initialize(db)
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield db


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS output_runs (
        id TEXT PRIMARY KEY, tool_key TEXT NOT NULL, scope_id TEXT,
        created REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS output_files (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, name TEXT NOT NULL,
        device INTEGER NOT NULL, inode INTEGER NOT NULL, size INTEGER NOT NULL,
        mtime_ns INTEGER NOT NULL, created REAL NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS output_runs_owner ON output_runs(tool_key,scope_id,created)")
    db.execute("CREATE INDEX IF NOT EXISTS output_files_run ON output_files(run_id,created)")


def register(run_id, owner, file_id, name, info):
    with database() as db:
        now = time.time()
        db.execute("INSERT OR IGNORE INTO output_runs VALUES(?,?,?,?)", (run_id, *owner, now))
        existing = db.execute("SELECT tool_key,scope_id FROM output_runs WHERE id=?", (run_id,)).fetchone()
        if existing != owner:
            raise ValueError("Invalid output owner")
        db.execute("INSERT INTO output_files VALUES(?,?,?,?,?,?,?,?)", (
            file_id, run_id, name, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, now,
        ))


def records(owner, *, file_id=None, limit=None):
    query = """SELECT f.*,r.scope_id FROM output_files f JOIN output_runs r ON r.id=f.run_id
        WHERE r.tool_key=? AND r.scope_id IS ?
"""
    parameters = list(owner)
    if file_id is not None:
        query += " AND f.id=?"
        parameters.append(file_id)
    query += " ORDER BY r.created DESC,r.id,f.created DESC,f.rowid DESC"
    if limit is not None:
        query += " LIMIT ?"
        parameters.append(max(1, int(limit)))
    with database(write=False) as db:
        cursor = db.execute(query, parameters)
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
