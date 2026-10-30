"""Publish an explicitly selected, conversation-bound preview without running it."""

import hashlib
import os
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from service.chat import ai_chat
from service.files import tool_inputs
from service.tools import preview_service, tool_activity
from service.tools.tool_runtime import validate_tool_entrypoint


@dataclass(frozen=True)
class PreviewSave:
    chat_id: str
    url: str
    project: str
    name: str
    content: bytes
    revision: str | None


def prepare(chat_id, url):
    parsed = urlsplit(url)
    parts = [unquote(part) for part in parsed.path.split('/')]
    if parsed.scheme or parsed.netloc or parsed.fragment or parts[1:2] != ['preview']:
        raise ValueError('invalid_preview')
    if len(parts) == 3:
        key = preview_service.validate_preview_key(parts[2])
    elif len(parts) == 4:
        key = preview_service.fixed_preview_key_from_path(parts[2], parts[3])
    else:
        key = None
    tokens = parse_qs(parsed.query).get('context', [])
    if not key or len(tokens) != 1:
        raise ValueError('invalid_preview')
    owner, bound_chat = tool_inputs.owner(tokens[0], key)
    if bound_chat != chat_id or not owner.startswith('tool:'):
        raise ValueError('invalid_preview')
    project, name = owner.removeprefix('tool:').split('/', 1)
    path = ai_chat.tool_path(project, name)
    raw_path = ai_chat.tools_dir() / project / f'{name}.py'
    if raw_path.is_symlink() or raw_path.parent.is_symlink():
        raise ValueError('invalid_target')
    if tool_activity.is_tool_running(project, name):
        raise tool_activity.ToolBusyError()
    content = preview_service.get_preview_file(key).read_bytes()
    validate_tool_entrypoint(content.decode('utf-8'))
    revision = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return PreviewSave(chat_id, url, project, name, content, revision)


def save(snapshot, *, overwrite=False):
    current = prepare(snapshot.chat_id, snapshot.url)
    if current != snapshot:
        raise ValueError('preview_or_target_changed')
    if current.revision is not None and not overwrite:
        raise ValueError('overwrite_confirmation_required')
    path = ai_chat.tool_path(current.project, current.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f'.{uuid4().hex}.tmp')
    try:
        temporary.write_bytes(current.content)
        if current.revision is None:
            os.link(temporary, path)  # Exclusive create: never overwrite a raced-in file.
        else:
            temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    from service.tools.tool_metadata import parse_tool_metadata
    ai_chat.bind_tool_chat(current.project, current.name, current.chat_id, parse_tool_metadata(current.content.decode('utf-8')).get('name'))
    return {'project': current.project, 'name': current.name}
