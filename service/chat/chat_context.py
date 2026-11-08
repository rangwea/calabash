"""Bound chat history by complete user turns without corrupting tool-call pairs."""

import json
from copy import deepcopy

from core.i18n import t
from service.files.file_readers import sent_files

MAX_HISTORY_CHARACTERS = 60000


def _bounded_source_read(content, arguments, limit):
    """Keep usable current evidence and explicit paging metadata, never a placeholder."""
    try:
        value = json.loads(content)
    except (ValueError, TypeError):
        value = None
    if content.startswith("Error:") or isinstance(value, dict) and ("error" in value or value.get("success") is False):
        return content
    if isinstance(value, dict) and isinstance(value.get("lines"), list):
        lines, size = [], 0
        for line in value["lines"]:
            cost = len(json.dumps(line, ensure_ascii=False))
            if lines and size + cost > limit:
                break
            lines.append(line)
            size += cost
        if len(lines) < len(value["lines"]):
            value.update(lines=lines, truncated=True,
                         next_offset=lines[-1]["line"] if lines else arguments.get("offset", 0))
        return json.dumps(value, ensure_ascii=False)
    text = value.get("content") if isinstance(value, dict) else content
    if not isinstance(text, str) or len(text) <= limit:
        return content
    end = text.rfind("\n", 0, limit)
    end = end + 1 if end >= 0 else limit
    excerpt = text[:end]
    next_offset = arguments.get("offset", 0) + max(0, excerpt.count("\n") - int(excerpt.startswith("@@ lines ")))
    hint = (f"\n[Source excerpt truncated for context. Read a smaller relevant page with "
            f"offset={next_offset}, limit=40, or search for the exact symbol. "
            "Do not repeat the same full-file read.]")
    if isinstance(value, dict):
        value.update(content=excerpt, truncated=True, next_offset=next_offset, paging_hint=hint.strip())
        return json.dumps(value, ensure_ascii=False)
    return excerpt + hint


def _compact_tool_sources(turn, budget):
    """Drop redundant executed source snapshots, never mutate saved messages."""
    compact = deepcopy(turn)
    results = {item.get("tool_call_id"): item.get("content", "") for item in compact if item["role"] == "tool"}
    omitted = False
    # Protect the newest read batch: otherwise a freshly returned source can
    # disappear before the model sees it, causing an endless reread cycle.
    read_names = {"read_tool", "read_tool_file"}
    protected, covered, retained = {}, {}, 0
    calls_by_id = {call.get("id"): call for message in compact for call in message.get("tool_calls", [])}
    mutations = {}
    positions = {call.get("id"): index for index, message in enumerate(compact) for call in message.get("tool_calls", [])}
    for index, message in enumerate(compact):
        for call in message.get("tool_calls", []):
            function = call.get("function", {})
            if function.get("name") not in {"write_tool_file", "patch_tool_file"} or call.get("id") not in results:
                continue
            try:
                arguments = json.loads(function.get("arguments", "{}"))
            except (ValueError, TypeError):
                continue
            if isinstance(arguments, dict):
                mutations[(arguments.get("project"), arguments.get("name"), arguments.get("path"))] = index
    for message in reversed(compact):
        call = calls_by_id.get(message.get("tool_call_id"), {})
        function = call.get("function", {})
        if function.get("name") not in read_names:
            continue
        try:
            arguments = json.loads(function.get("arguments", "{}"))
        except (ValueError, TypeError):
            continue
        if not isinstance(arguments, dict):
            continue
        content = message.get("content", "")
        if not isinstance(content, str) or "omitted." in content or content.startswith("Error:"):
            continue
        path = arguments.get("file_path", arguments.get("path"))
        if positions[call["id"]] < mutations.get((arguments.get("project"), arguments.get("name"), path), -1):
            continue
        key = (function.get("name"), path, arguments.get("project"), arguments.get("name"))
        offset, length = arguments.get("offset", 0), arguments.get("limit", 100)
        if not isinstance(offset, int) or not isinstance(length, int):
            continue
        span = set(range(max(0, offset), max(0, offset) + min(max(0, length), 2000)))
        if key in covered and span <= covered[key]:
            continue
        cost = len(json.dumps(content, ensure_ascii=False))
        if protected and retained + cost > budget * .65:
            continue
        protected[call["id"]] = arguments
        covered.setdefault(key, set()).update(span)
        retained += min(cost, 12000)
    for item in compact:
        for call in item.get("tool_calls", []):
            function = call.get("function", {})
            if call.get("id") not in results or function.get("name") not in {
                "write_tool", "write_tool_file", "patch_tool_file"
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
            fields = ("old", "new", "content")
            if isinstance(arguments.get("files"), dict):
                arguments["files"] = {path: "[Executed source omitted. Read current draft before editing.]" for path in arguments["files"]}
                omitted = True
                function["arguments"] = json.dumps(arguments, ensure_ascii=False)
            if not any(isinstance(arguments.get(field), str) for field in fields):
                continue
            for field in fields:
                if isinstance(arguments.get(field), str):
                    arguments[field] = "[Executed source snapshot omitted. Read the real working file before editing.]"
            function["arguments"] = json.dumps(arguments, ensure_ascii=False)
            omitted = True
    # Retain the newest source read whenever it fits. Older reads can be stale
    # after a write; preserve revision metadata while releasing their code text.
    for item in compact:
        if len(json.dumps(compact, ensure_ascii=False)) <= budget:
            break
        if item["role"] != "tool" or item.get("tool_call_id") in protected:
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
    reference_reads = {call.get("id"): call.get("function", {}).get("name")
                       for item in compact for call in item.get("tool_calls", [])
                       if call.get("function", {}).get("name") in {
                           "read_ui_reference", "read_ui_preset", "read_component_api", "read_api_contract", "read_tool_file"}}
    for item in compact:
        if len(json.dumps(compact, ensure_ascii=False)) <= budget:
            break
        name = reference_reads.get(item.get("tool_call_id"))
        if item["role"] != "tool" or not name or item.get("tool_call_id") in protected:
            continue
        try:
            result = json.loads(item.get("content", ""))
        except (ValueError, TypeError):
            if name in {"read_ui_reference", "read_tool_file"} and not item.get("content", "").startswith("Error:"):
                item["content"] = "[UI reference omitted. Read the named reference again only if needed.]"
                omitted = True
            continue
        if isinstance(result, dict) and "error" not in result and result.get("success") is not False:
            # Preserve identity/revision and retrieval metadata, discard only
            # repeatable successful reference/source payloads.
            for key in ("files", "rules", "tokens", "example", "content", "lines", "declarations", "models", "operations"):
                if key in result:
                    result[key] = "[Snapshot omitted. Query this reference or current source only if needed.]"
            item["content"] = json.dumps(result, ensure_ascii=False)
            omitted = True
    if len(json.dumps(compact, ensure_ascii=False)) > budget:
        allowance = min(12000, max(1000, budget // 2))
        for message in compact:
            if message.get("tool_call_id") in protected:
                old = message.get("content", "")
                message["content"] = _bounded_source_read(old, protected[message["tool_call_id"]], allowance)
                omitted = omitted or old != message["content"]
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
            item["content"] += "\n\nAttached local files (metadata only; image pixels may be supplied separately; use read_attachment for document contents):\n" + json.dumps(attached, ensure_ascii=False)
        turns[-1].append(item)
    kept = []
    budget = MAX_HISTORY_CHARACTERS
    compacted = False
    for turn in reversed(turns):
        cost = len(json.dumps(turn, ensure_ascii=False))
        if cost > budget:
            turn, omitted = _compact_tool_sources(turn, budget)
            compacted = compacted or omitted
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
