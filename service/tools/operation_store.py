"""Tool operation receipts and source observations; no chat or model state."""

import json
import os
import sqlite3
from contextlib import closing

from core.local_paths import app_dir


def root():
    path = app_dir() / "agent"
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
    return path


def connect():
    path = root() / "operations.sqlite"
    db = sqlite3.connect(path, timeout=15)
    if os.name != "nt":
        path.chmod(0o600)
    db.execute("CREATE TABLE IF NOT EXISTS receipts(run_id TEXT, call_id TEXT, arguments TEXT NOT NULL, result TEXT, PRIMARY KEY(run_id,call_id))")
    db.execute("CREATE TABLE IF NOT EXISTS source_observations(chat_id TEXT,project TEXT,name TEXT,path TEXT,fingerprint TEXT NOT NULL,PRIMARY KEY(chat_id,project,name,path))")
    db.commit()
    return db


def begin(run_id, call_id, arguments):
    """Reserve before a side effect. Unknown outcomes require a fresh user action."""
    with closing(connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT arguments,result FROM receipts WHERE run_id=? AND call_id=?", (run_id, call_id)).fetchone()
        if row:
            if row[0] != arguments:
                return {"error": "Operation arguments changed; read current tool before editing"}
            return json.loads(row[1]) if row[1] is not None else {"error": "Previous save outcome is uncertain. Read current tool and create a new operation; it was not automatically repeated."}
        db.execute("INSERT INTO receipts VALUES(?,?,?,NULL)", (run_id, call_id, arguments))
    return None


def finish(run_id, call_id, result):
    with closing(connect()) as db, db:
        db.execute("UPDATE receipts SET result=? WHERE run_id=? AND call_id=?", (json.dumps(result, ensure_ascii=False), run_id, call_id))


def observe_source(chat_id, project, name, path, fingerprint):
    with closing(connect()) as db, db:
        db.execute('INSERT OR REPLACE INTO source_observations VALUES(?,?,?,?,?)', (chat_id, project, name, path, fingerprint))


def observed_source(chat_id, project, name, path):
    with closing(connect()) as db:
        row = db.execute('SELECT fingerprint FROM source_observations WHERE chat_id=? AND project=? AND name=? AND path=?', (chat_id, project, name, path)).fetchone()
    return row[0] if row else None
