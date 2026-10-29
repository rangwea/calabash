"""Bound chat history by complete user turns without corrupting tool-call pairs."""

import json
from copy import deepcopy

from core.i18n import t
from service.files.file_readers import sent_files

MAX_HISTORY_CHARACTERS = 60000


def _compact_tool_sources(turn, budget):
    """Drop redundant executed source snapshots, never mutate saved messages."""
    compact = deepcopy(turn)
    results = {item.get("tool_call_id"): item.get("content", "") for item in compact if item["role"] == "tool"}
    omitted = False
    for item in compact:
        for call in item.get("tool_calls", []):
            function = call.get("function", {})
            if call.get("id") not in results or function.get("name") not in {
                "write_tool", "validate_tool", "preview_tool", "write_file", "edit_file"
            }:
                continue
            try:
                arguments = json.loads(function.get("arguments", "{}"))
            except (ValueError, TypeError):
                continue
            try:
                outcome = json.loads(results[call["id"]])
            except (ValueError, TypeError):
                outcome = None
            if isinstance(outcome, dict) and ("error" in outcome or outcome.get("success") is False):
                continue  # Failed code may be the only draft; keep it for correction.
            if results[call["id"]].startswith("Error:"):
                continue
            if not isinstance(arguments, dict):
                continue
            fields = ("old_string", "new_string") if function.get("name") == "edit_file" else ("content",)
            if not any(isinstance(arguments.get(field), str) for field in fields):
                continue
            for field in fields:
                if isinstance(arguments.get(field), str):
                    arguments[field] = "[Executed source snapshot omitted. Read current tool or virtual draft before editing.]"
            function["arguments"] = json.dumps(arguments, ensure_ascii=False)
            omitted = True
    # Retain the newest source read whenever it fits. Older reads can be stale
    # after a write; preserve revision metadata while releasing their code text.
    for item in compact:
        if len(json.dumps(compact, ensure_ascii=False)) <= budget:
            break
        if item["role"] != "tool":
            continue
        try:
            result = json.loads(item.get("content", ""))
        except (ValueError, TypeError):
            continue
        read_ids = {
            call.get("id") for message in compact
            for call in message.get("tool_calls", [])
            if call.get("function", {}).get("name") == "read_tool"
        }
        if item.get("tool_call_id") in read_ids and isinstance(result, dict) and isinstance(result.get("content"), str):
            result["content"] = "[Source snapshot omitted. Read this tool again before editing.]"
            item["content"] = json.dumps(result, ensure_ascii=False)
            omitted = True
    # Draft reads may contain a full source snapshot as plain text. The current
    # virtual file is restored from the conversation checkpoint, not this copy.
    draft_reads = {call.get("id") for item in compact for call in item.get("tool_calls", [])
                   if call.get("function", {}).get("name") == "read_file"}
    for item in compact:
        if len(json.dumps(compact, ensure_ascii=False)) <= budget:
            break
        if item.get("role") == "tool" and item.get("tool_call_id") in draft_reads and not item.get("content", "").startswith("Error:"):
            item["content"] = "[Virtual draft read omitted. Use read_file for its current content.]"
            omitted = True
    return compact, omitted


def prepare(messages, chat_id=None, *, include_reasoning=True):
    references = {item["id"]: item for item in sent_files(chat_id)} if chat_id else {}
    systems = [dict(message) for message in messages if message["role"] == "system"]
    turns = []
    for message in messages:
        if message["role"] == "system":
            continue
        if message["role"] == "user" or not turns:
            turns.append([])
        item = dict(message)
        if not include_reasoning:
            item.pop("reasoning_content", None)
        attached = [references[file_id] for file_id in message.get("attachments", []) if file_id in references]
        if attached:
            item["content"] += "\n\nAttached local files (metadata only; use read_attachment for contents):\n" + json.dumps(attached, ensure_ascii=False)
        turns[-1].append(item)
    kept = []
    budget = MAX_HISTORY_CHARACTERS
    compacted = False
    for turn in reversed(turns):
        cost = len(json.dumps(turn, ensure_ascii=False))
        if cost > budget and not kept:
            turn, compacted = _compact_tool_sources(turn, budget)
            cost = len(json.dumps(turn, ensure_ascii=False))
        if cost > budget:
            if not kept:
                raise ValueError(t("当前任务内容过长，请拆分需求或新建对话"))
            break
        kept.insert(0, turn)
        budget -= cost
    if len(kept) < len(turns):
        systems.append({"role": "system", "content": "Earlier complete turns were omitted to limit context. Never assume old tool code is current; read_tool before editing."})
    if compacted:
        systems.append({"role": "system", "content": "Source snapshots in already executed tool calls were omitted to save context. Their results and call IDs are retained; do not repeat completed writes or previews just because source was omitted. Use read_tool to obtain current code and revision before editing. Omitted source placeholders are not executable code."})
    return systems + [message for turn in kept for message in turn]
