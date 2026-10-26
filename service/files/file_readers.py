"""Authorized, cancelable file reading for the active conversation."""

import asyncio
import json
import sys
from pathlib import Path

from service.files import conversation_files as files

WORKER_TIMEOUT = 30


def error(code):
    return {"error": {"code": code}, "untrusted_data": True}


def sent_files(chat_id):
    with files.database() as db:
        ids = {row[0] for row in db.execute("SELECT file_id FROM message_files WHERE chat_id=?", (chat_id,))}
    return [item for item in files.list_files(chat_id) if item["id"] in ids]


def authorized_record(chat_id, file_id):
    if not chat_id or not any(item["id"] == file_id for item in sent_files(chat_id)):
        return None
    return files.get_record(chat_id, file_id)


def worker_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--file-reader"]
    return [sys.executable, "-m", "service.files.file_reader_worker"]


async def read_attachment(chat_id, file_id, *, sheet=None, offset=0, limit=20):
    if type(offset) is not int or not 0 <= offset <= 1000000 or type(limit) is not int or not 1 <= limit <= 100 or (sheet is not None and (not isinstance(sheet, str) or len(sheet) > 128)):
        return error("invalid_options")
    record = await asyncio.to_thread(authorized_record, chat_id, file_id)
    if not record:
        return error("not_found")
    status = await asyncio.to_thread(files.check, chat_id, file_id)
    if status != "ready":
        return error(status)
    process = await asyncio.create_subprocess_exec(*worker_command(), cwd=str(Path(__file__).resolve().parents[2]),
                                                 stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    payload = json.dumps({"record": record, "options": {"sheet": sheet, "offset": offset, "limit": limit}}).encode()
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(payload), WORKER_TIMEOUT)
        if process.returncode != 0 or len(stdout) > 256 * 1024:
            return error("corrupt")
        result = json.loads(stdout)
        # Recheck after parsing: a removed or revoked reference must not disclose contents.
        if not await asyncio.to_thread(authorized_record, chat_id, file_id):
            return error("not_found")
        status = await asyncio.to_thread(files.check, chat_id, file_id)
        if status != "ready":
            return error(status)
        return {**result, "untrusted_data": True}
    except TimeoutError:
        return error("timeout")
    except (ValueError, OSError):
        return error("corrupt")
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
