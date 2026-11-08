"""Application-owned operation receipts, separate from LangGraph's own tables."""

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
    db.execute("CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, chat_id TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS receipts(run_id TEXT, call_id TEXT, arguments TEXT NOT NULL, result TEXT, PRIMARY KEY(run_id,call_id))")
    db.execute("CREATE TABLE IF NOT EXISTS code_targets(run_id TEXT,project TEXT,name TEXT,binding TEXT NOT NULL,PRIMARY KEY(run_id,project,name))")
    db.execute("CREATE TABLE IF NOT EXISTS source_observations(chat_id TEXT,project TEXT,name TEXT,path TEXT,fingerprint TEXT NOT NULL,PRIMARY KEY(chat_id,project,name,path))")
    db.commit()
    return db


def register(run_id, chat_id):
    with closing(connect()) as db, db:
        db.execute("INSERT OR IGNORE INTO runs VALUES(?,?)", (run_id, chat_id or ""))


def owned(run_id, chat_id):
    with closing(connect()) as db:
        return bool(db.execute("SELECT 1 FROM runs WHERE id=? AND chat_id=?", (run_id, chat_id or "")).fetchone())


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


def delete_chat(chat_id):
    # Use the checkpointer's public API rather than editing its internal tables.
    from langgraph.checkpoint.sqlite import SqliteSaver

    from service.chat.agent_usage import delete_runs
    with closing(connect()) as db, db:
        runs = [row[0] for row in db.execute("SELECT id FROM runs WHERE chat_id=?", (chat_id,))]
        path = root() / "checkpoints.sqlite"
        if runs and path.exists():
            with SqliteSaver.from_conn_string(str(path)) as saver:
                for run_id in runs:
                    saver.delete_thread(run_id)
        delete_runs(runs)
        db.execute("DELETE FROM source_observations WHERE chat_id=?", (chat_id,))
        for run_id in runs:
            db.execute("DELETE FROM receipts WHERE run_id=?", (run_id,))
            db.execute("DELETE FROM code_targets WHERE run_id=?", (run_id,))
        db.execute("DELETE FROM runs WHERE chat_id=?", (chat_id,))


def target(run_id, project, name):
    with closing(connect()) as db:
        row = db.execute('SELECT binding FROM code_targets WHERE run_id=? AND project=? AND name=?', (run_id, project, name)).fetchone()
    return json.loads(row[0]) if row else None


def bind_target(run_id, project, name, binding):
    with closing(connect()) as db, db:
        db.execute('INSERT OR IGNORE INTO code_targets VALUES(?,?,?,?)', (run_id, project, name, json.dumps(binding)))


def observe_source(chat_id, project, name, path, fingerprint):
    with closing(connect()) as db, db:
        db.execute('INSERT OR REPLACE INTO source_observations VALUES(?,?,?,?,?)', (chat_id, project, name, path, fingerprint))


def observed_source(chat_id, project, name, path):
    with closing(connect()) as db:
        row = db.execute('SELECT fingerprint FROM source_observations WHERE chat_id=? AND project=? AND name=? AND path=?', (chat_id, project, name, path)).fetchone()
    return row[0] if row else None
