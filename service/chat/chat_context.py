"""Bound chat history by complete user turns without corrupting tool-call pairs."""

import json

from core.i18n import t
from service.files.file_readers import sent_files

MAX_HISTORY_CHARACTERS = 60000


def prepare(messages, chat_id=None):
    references = {item["id"]: item for item in sent_files(chat_id)} if chat_id else {}
    systems = [dict(message) for message in messages if message["role"] == "system"]
    turns = []
    for message in messages:
        if message["role"] == "system":
            continue
        if message["role"] == "user" or not turns:
            turns.append([])
        item = dict(message)
        attached = [references[file_id] for file_id in message.get("attachments", []) if file_id in references]
        if attached:
            item["content"] += "\n\nAttached local files (metadata only; use read_attachment for contents):\n" + json.dumps(attached, ensure_ascii=False)
        turns[-1].append(item)
    kept = []
    budget = MAX_HISTORY_CHARACTERS
    for turn in reversed(turns):
        cost = len(json.dumps(turn, ensure_ascii=False))
        if cost > budget:
            if not kept:
                raise ValueError(t("当前任务内容过长，请拆分需求或新建对话"))
            break
        kept.insert(0, turn)
        budget -= cost
    if len(kept) < len(turns):
        systems.append({"role": "system", "content": "Earlier complete turns were omitted to limit context. Never assume old tool code is current; read_tool before editing."})
    return systems + [message for turn in kept for message in turn]
