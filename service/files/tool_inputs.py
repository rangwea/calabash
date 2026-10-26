"""Opaque, preview-bound file contexts; no local paths in preview URLs."""

import json
import time
from uuid import uuid4

from service.files import conversation_files as files
from service.files.file_readers import authorized_record


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS tool_input_contexts (
        id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, preview_key TEXT NOT NULL,
        file_ids TEXT NOT NULL, created REAL NOT NULL,
        tool_key TEXT NOT NULL DEFAULT '')""")


def create(chat_id, preview_key, messages, *, tool_key=""):
    ids = next((message.get("attachments") for message in reversed(messages) if message.get("role") == "user" and message.get("attachments")), [])
    if any(not authorized_record(chat_id, file_id) for file_id in ids):
        raise ValueError("invalid_reference")
    token = uuid4().hex
    with files.database() as db:
        files.ensure_chat(db, chat_id)
        db.execute("DELETE FROM tool_input_contexts WHERE created < ?", (time.time() - 7 * 86400,))
        db.execute("INSERT INTO tool_input_contexts(id,chat_id,preview_key,file_ids,created,tool_key) VALUES(?,?,?,?,?,?)", (token, chat_id, preview_key, json.dumps(ids), time.time(), tool_key))
    return token


def _context(token, preview_key):
    with files.database() as db:
        row = db.execute("""SELECT x.chat_id,x.file_ids,x.created,x.tool_key FROM tool_input_contexts x
            JOIN chats c ON c.id=x.chat_id WHERE x.id=? AND x.preview_key=? AND c.deleted=0""", (token, preview_key)).fetchone()
    if not row or time.time() - row[2] > 7 * 86400:
        raise ValueError("invalid_context")
    return row


def owner(token, preview_key):
    """Resolve a native/server-issued preview context to its result owner."""
    row = _context(token, preview_key)
    return row[3] or f"preview:{preview_key}", row[0]


def resolve(token, preview_key):
    row = _context(token, preview_key)
    ids = json.loads(row[1])
    result = []
    for file_id in ids:
        record = authorized_record(row[0], file_id)
        if record:
            result.append(record)
    if ids and not result:
        raise ValueError("invalid_context")
    return result


def current_inputs():
    """Return validated default inputs in main() and NiceGUI event callbacks."""
    try:
        from nicegui import ui
        context = getattr(ui.context.client, "calabash_input_context", None)
    except RuntimeError:
        return []
    if not context:
        return []
    return resolve(*context)
