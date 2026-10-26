"""SQLite metadata for tool-owned result files; never deletes file contents."""

import time

from service.files.conversation_files import database


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS output_runs (
        id TEXT PRIMARY KEY, tool_key TEXT NOT NULL, chat_id TEXT,
        created REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS output_files (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, name TEXT NOT NULL,
        device INTEGER NOT NULL, inode INTEGER NOT NULL, size INTEGER NOT NULL,
        mtime_ns INTEGER NOT NULL, created REAL NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS output_runs_owner ON output_runs(tool_key,chat_id,created)")
    db.execute("CREATE INDEX IF NOT EXISTS output_files_run ON output_files(run_id,created)")


def require_live_chat(db, chat_id):
    if chat_id is not None:
        row = db.execute("SELECT deleted FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not row or row[0]:
            raise ValueError("Output conversation is no longer available")


def check_owner(owner):
    with database() as db:
        require_live_chat(db, owner[1])


def register(run_id, owner, file_id, name, info):
    with database() as db:
        require_live_chat(db, owner[1])
        now = time.time()
        db.execute("INSERT OR IGNORE INTO output_runs VALUES(?,?,?,?)", (run_id, *owner, now))
        existing = db.execute("SELECT tool_key,chat_id FROM output_runs WHERE id=?", (run_id,)).fetchone()
        if existing != owner:
            raise ValueError("Invalid output owner")
        db.execute("INSERT INTO output_files VALUES(?,?,?,?,?,?,?,?)", (
            file_id, run_id, name, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, now,
        ))


def records(owner, *, file_id=None, limit=None):
    query = """SELECT f.*,r.chat_id FROM output_files f JOIN output_runs r ON r.id=f.run_id
        WHERE r.tool_key=? AND r.chat_id IS ?
        AND (r.chat_id IS NULL OR EXISTS (SELECT 1 FROM chats c WHERE c.id=r.chat_id AND c.deleted=0))"""
    parameters = list(owner)
    if file_id is not None:
        query += " AND f.id=?"
        parameters.append(file_id)
    query += " ORDER BY r.created DESC,r.id,f.created DESC,f.rowid DESC"
    if limit is not None:
        query += " LIMIT ?"
        parameters.append(max(1, int(limit)))
    with database() as db:
        cursor = db.execute(query, parameters)
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def delete_chat_references(db, chat_id):
    db.execute("DELETE FROM output_files WHERE run_id IN (SELECT id FROM output_runs WHERE chat_id=?)", (chat_id,))
    db.execute("DELETE FROM output_runs WHERE chat_id=?", (chat_id,))
