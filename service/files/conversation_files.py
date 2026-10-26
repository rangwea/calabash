"""Conversation-scoped file references. This module never reads file contents for AI."""

import json
import os
import re
import stat
import time
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4

MAX_FILES = 20
UPLOAD_LIMIT = 50 * 1024 * 1024


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS chat_files (
        id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, original_path TEXT NOT NULL,
        path TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL,
        mtime_ns INTEGER NOT NULL, device INTEGER NOT NULL, inode INTEGER NOT NULL,
        source TEXT NOT NULL, created REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS message_files (
        chat_id TEXT NOT NULL, message_id TEXT NOT NULL, file_id TEXT NOT NULL,
        PRIMARY KEY(chat_id, message_id, file_id))""")
    db.execute("CREATE INDEX IF NOT EXISTS chat_files_chat ON chat_files(chat_id)")
    db.execute("CREATE INDEX IF NOT EXISTS message_files_file ON message_files(file_id)")


@contextmanager
def database():
    from service.chat.ai_chat import connect
    with closing(connect()) as db, db:
        # Serialize count/check/register and deletion to avoid attachment races.
        db.execute("BEGIN IMMEDIATE")
        yield db


def ensure_chat(db, chat_id):
    from core.i18n import t
    row = db.execute("SELECT deleted FROM chats WHERE id=?", (chat_id,)).fetchone()
    if row and row[0]:
        raise ValueError("deleted")
    if not row:
        db.execute("INSERT INTO chats(id,title,messages) VALUES(?,?, '[]')", (chat_id, t("新对话")))


def _records(db, chat_id, pending=False):
    query = "SELECT f.* FROM chat_files f JOIN chats c ON c.id=f.chat_id WHERE f.chat_id=? AND c.deleted=0"
    if pending:
        query += " AND NOT EXISTS (SELECT 1 FROM message_files m WHERE m.file_id=f.id)"
    cursor = db.execute(query + " ORDER BY f.created, f.id", (chat_id,))
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _public(record):
    return {key: record[key] for key in ("id", "name", "size", "source")}


def list_files(chat_id, *, pending=False):
    with database() as db:
        return [_public(row) for row in _records(db, chat_id, pending)]


def get_record(chat_id, file_id):
    with database() as db:
        return next((row for row in _records(db, chat_id) if row["id"] == file_id), None)


def _snapshot(path):
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


def register(chat_id, path, *, source="native", name=None):
    original, resolved, info = _snapshot(path)
    with database() as db:
        ensure_chat(db, chat_id)
        drafts = _records(db, chat_id, pending=True)
        for row in drafts:
            if row["original_path"] == str(original) and row["path"] == str(resolved) and row["mtime_ns"] == info.st_mtime_ns and row["size"] == info.st_size and row["inode"] == info.st_ino:
                return _public(row)
        if len(drafts) >= MAX_FILES:
            raise ValueError("limit")
        row = {"id": uuid4().hex, "chat_id": chat_id, "original_path": str(original), "path": str(resolved),
               "name": name or original.name, "size": info.st_size, "mtime_ns": info.st_mtime_ns,
               "device": info.st_dev, "inode": info.st_ino, "source": source, "created": time.time()}
        db.execute(f"INSERT INTO chat_files({','.join(row)}) VALUES({','.join('?' for _ in row)})", tuple(row.values()))
        return _public(row)


def check(chat_id, file_id):
    row = get_record(chat_id, file_id)
    if not row:
        return "missing"
    try:
        _, resolved, info = _snapshot(row["original_path"])
        if (str(resolved), info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino) != (row["path"], row["size"], row["mtime_ns"], row["device"], row["inode"]):
            return "changed"
        return "ready"
    except PermissionError:
        return "denied"
    except (OSError, ValueError):
        return "missing"


def remove_pending(chat_id, file_id):
    with database() as db:
        return bool(db.execute("""DELETE FROM chat_files WHERE chat_id=? AND id=?
            AND NOT EXISTS (SELECT 1 FROM message_files WHERE file_id=?)""",
                               (chat_id, file_id, file_id)).rowcount)


def bind_messages(db, chat_id, messages):
    stored = db.execute("SELECT messages FROM chats WHERE id=?", (chat_id,)).fetchone()
    historical = {message["id"]: message.get("attachments", []) for message in json.loads(stored[0])
                  if message.get("role") == "user" and message.get("id")} if stored else {}
    for message in messages:
        if message.get("role") != "user":
            continue
        message.setdefault("id", uuid4().hex)
        ids = message.get("attachments", [])
        if not isinstance(ids, list) or len(ids) > MAX_FILES or any(not isinstance(item, str) for item in ids):
            raise ValueError("limit")
        if message["id"] in historical and set(ids) != set(historical[message["id"]]):
            raise ValueError("already_sent")
        for file_id in ids:
            row = db.execute("SELECT chat_id FROM chat_files WHERE id=?", (file_id,)).fetchone()
            if not row or row[0] != chat_id:
                raise ValueError("invalid_reference")
            bound = db.execute("SELECT message_id FROM message_files WHERE file_id=?", (file_id,)).fetchone()
            if bound and bound[0] != message["id"]:
                raise ValueError("already_sent")
            db.execute("INSERT OR IGNORE INTO message_files VALUES(?,?,?)", (chat_id, message["id"], file_id))


def for_message(chat_id, message_id):
    with database() as db:
        ids = {row[0] for row in db.execute("SELECT file_id FROM message_files WHERE chat_id=? AND message_id=?", (chat_id, message_id))}
        return [_public(row) for row in _records(db, chat_id) if row["id"] in ids]


def consume_selection(chat_id, token):
    directory = os.environ.get("CALABASH_SELECTION_DIR")
    if not directory or not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32}", token):
        raise ValueError("invalid_selection")
    path = Path(directory) / f"{token}.json"
    try:
        # Rename claims a single-use native-issued ticket before reading it.
        claimed = path.with_suffix(f".{uuid4().hex}.claimed")
        path.rename(claimed)
        try:
            data = json.loads(claimed.read_text())
        finally:
            claimed.unlink(missing_ok=True)
        if not 0 <= time.time() - data["created"] <= 300:
            raise ValueError("invalid_selection")
        paths = data["paths"]
        if not isinstance(paths, list) or len(paths) > MAX_FILES:
            raise ValueError("limit")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid_selection") from error
    # Invalid individual files must not prevent valid siblings being attached.
    results = []
    for selected in paths:
        try:
            results.append(register(chat_id, selected))
        except (OSError, ValueError) as error:
            results.append({"error": str(error) if isinstance(error, ValueError) else "unavailable"})
    return results


def upload_dir():
    from service.chat.ai_chat import app_dir
    return app_dir() / "uploads"


async def store_upload(chat_id, upload):
    if upload.size() > UPLOAD_LIMIT:
        raise ValueError("upload_limit")
    root = upload_dir().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / uuid4().hex
    name = upload.name.replace("\\", "/").rsplit("/", 1)[-1] or "file"
    total = 0
    try:
        with path.open("xb") as output:
            path.chmod(0o600)
            async for chunk in upload.iterate():
                total += len(chunk)
                if total > UPLOAD_LIMIT:
                    raise ValueError("upload_limit")
                output.write(chunk)
        return register(chat_id, path, source="upload", name=name)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def cleanup_uploads(*, now=None):
    root = upload_dir().resolve()
    if not root.exists():
        return
    with database() as db:
        referenced = {row[0] for row in db.execute("SELECT path FROM chat_files WHERE source='upload'")}
    cutoff = (time.time() if now is None else now) - 86400
    try:
        candidates = list(root.iterdir())
    except OSError:
        return
    for path in candidates:
        if re.fullmatch(r"[a-f0-9]{32}", path.name) and str(path) not in referenced:
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass
