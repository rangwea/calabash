"""Single-agent execution, local checkpoints and the desktop streaming contract."""

import hashlib
import json
import os
from uuid import uuid4

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware import ModelCallLimitMiddleware, TodoListMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import (
    AIMessage,
    SystemMessage,
    ToolMessage,
    convert_to_messages,
    convert_to_openai_messages,
)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import GraphRecursionError
from langsmith import tracing_context

from core.i18n import t
from service.chat import agent_store
from service.chat.agent_model import (
    CalabashChatModel,
    OutputLimitError,
    PublicAgentError,
)
from service.chat.bundle_agent_tools import build_tools

MODEL_CALLS_PER_RUN = 40
_active_runs = set()
_active_chats = set()

# Explicitly remove delegation. Filesystem tools below operate only on graph
# state; there is no local filesystem or shell backend.
register_harness_profile("calabash:local", HarnessProfile(
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
))


class CompletedContextMiddleware(AgentMiddleware):
    """Release repeatable completed payloads before costly summarization."""

    async def abefore_model(self, state, runtime):
        from service.chat.chat_context import _compact_tool_sources
        messages = state["messages"]
        wire = [convert_to_openai_messages(message) for message in messages]
        if len(json.dumps(wire, ensure_ascii=False)) <= 40000:
            return None
        compact, changed = _compact_tool_sources(wire, 40000)
        if not changed:
            return None
        updates = []
        for message, before, after in zip(messages, wire, compact, strict=True):
            if not message.id or before == after:
                continue
            if isinstance(message, AIMessage):
                arguments = {call["id"]: json.loads(call["function"]["arguments"])
                             for call in after.get("tool_calls", [])}
                calls = [{**call, "args": arguments.get(call["id"], call["args"])} for call in message.tool_calls]
                updates.append(message.model_copy(update={"tool_calls": calls}))
            elif isinstance(message, ToolMessage):
                updates.append(message.model_copy(update={"content": after["content"]}))
        if updates:
            updates.append(SystemMessage(
                content="Completed source/reference snapshots were omitted to save context. Their results and call IDs remain; do not repeat completed writes. Current virtual files remain available. Read only the relevant current file before editing; omitted placeholders are not executable code.",
                id="calabash-context-hint",
            ))
            return {"messages": updates}


class NoProgressMiddleware(AgentMiddleware):
    """Bound read-only investigation by actual source progress, per invocation."""

    def __init__(self):
        self.seen = set()
        self.last_count = None
        self.idle = 0
        self.warned = False
        self.signatures = []
        self.delivery_prompted = False

    async def abefore_model(self, state, runtime):
        messages = state["messages"]
        results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
        calls = [(c, results[c["id"]]) for m in messages if isinstance(m, AIMessage)
                 for c in m.tool_calls if c["id"] in results]
        # Source content, not timestamps or varying read offsets, is progress.
        sources = {path: value.get("content") for path, value in state.get("files", {}).items()
                   if path.startswith("/drafts/")}
        evidence = []
        for call, result in calls:
            if call["name"] in {"write_tool", "patch_tool_file", "deliver_draft", "check_tool_build", "validate_tool"}:
                evidence.append((call["name"], result.content))
        fingerprint = hashlib.sha256(json.dumps((sources, evidence[-1:]), sort_keys=True, default=str).encode()).hexdigest()
        count = len(calls)
        if self.last_count is not None and count > self.last_count:
            self.signatures.extend(json.dumps((call["name"], call["args"]), sort_keys=True)
                                   for call, _ in calls[self.last_count:])
            self.signatures = self.signatures[-4:]
            if fingerprint in self.seen and len(self.signatures) == 4 and len(set(self.signatures)) == 1:
                raise PublicAgentError(t("检测到重复操作，已暂停；请补充要求后继续"))
        if self.last_count is None or fingerprint not in self.seen:
            self.idle = 0
        elif count > self.last_count:
            self.idle += 1
        self.seen.add(fingerprint)
        self.last_count = count
        if self.idle >= 14:
            raise PublicAgentError(t("检测到重复操作，已暂停；请补充要求后继续"))
        if (not self.delivery_prompted and calls and messages
                and isinstance(messages[-1], ToolMessage)):
            call, result = calls[-1]
            path = call["args"].get("file_path")
            if (call["name"] in {"write_file", "edit_file"} and isinstance(path, str)
                    and path.startswith("/drafts/") and result.status != "error"
                    and not str(result.content).startswith("Error:")):
                parts = path.split("/")
                if len(parts) >= 5 and parts[2] and parts[3]:
                    prefix = "/".join(parts[:4]) + "/"
                    required = ("tool.json", "frontend/App.vue", "backend/main.py")
                    if all(sources.get(prefix + file) for file in required):
                        self.delivery_prompted = True
                        return {"messages": [SystemMessage(
                            content=(
                                f"Draft delivery checkpoint: {prefix} contains all required files. "
                                "If the requested minimum behavior is implemented, call deliver_draft now "
                                "with the current revision when required, then check_tool_build. "
                                "Skip full-file rereads and rewrites for confidence. If the build fails, "
                                "use its diagnostic to inspect the relevant lines and make a targeted edit. "
                                "File presence alone does not prove completeness. Never publish here."
                            ),
                            id="calabash-delivery-hint",
                        )]}
        if self.idle >= 6 and not self.warned:
            self.warned = True
            return {"messages": [SystemMessage(
                content="Investigation has made no source or validation progress for several rounds. Stop rereading whole files or references. If the virtual draft contains tool.json, frontend/App.vue and backend/main.py, use deliver_draft now, then check_tool_build. Fix only concrete diagnostics with a targeted edit. If blocked, explain the missing information instead of repeating calls. Do not publish or perform business actions without authorization.",
                id="calabash-progress-hint",
            )]}


class ToolRequestMiddleware(AgentMiddleware):
    """Return bounded request failures to the model without leaking exception data."""

    @staticmethod
    def failure(request, error):
        from service.tools.tool_bundles import ToolUnavailable
        if isinstance(error, ToolUnavailable):
            code, message = error.code, str(error)
        elif isinstance(error, FileNotFoundError):
            code, message = 'file_not_found', 'Requested file is unavailable. Read the current tool file list before retrying.'
        elif isinstance(error, KeyError):
            code, message = 'unknown_field_or_file', 'Requested field or source file is unavailable. Inspect the current tool and supported API.'
        elif isinstance(error, SyntaxError):
            code, message = 'invalid_source', 'Source validation failed. Check syntax in the current draft before saving.'
        else:
            code, message = 'request_rejected', 'Request rejected. Check current revision, arguments and permissions; query documented APIs. Authorization requirements still apply.'
        return ToolMessage(content=json.dumps({'error': code, 'message': message}),
                           tool_call_id=request.tool_call['id'], name=request.tool_call['name'], status='error')

    def wrap_tool_call(self, request, handler):
        try:
            return handler(request)
        except (ValueError, KeyError, FileNotFoundError, PermissionError, SyntaxError) as error:
            return self.failure(request, error)

    async def awrap_tool_call(self, request, handler):
        try:
            return await handler(request)
        except (ValueError, KeyError, FileNotFoundError, PermissionError, SyntaxError) as error:
            return self.failure(request, error)


def run_identity(messages, chat_id, provider, model, connection, repair):
    user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    if user is None:
        raise ValueError("A user message is required")
    user.setdefault("agent_run_id", uuid4().hex)
    # Hash, never persist the API key or connection object in graph config.
    identity = [chat_id, user["agent_run_id"], provider, model, connection,
                repair.get("attempt", repair.get("id")) if repair else None]
    run_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    if user.get("agent_checkpoint_id") != run_id:
        user["agent_completed"] = False
    user["agent_checkpoint_id"] = run_id
    user["agent_repair"] = bool(repair)
    return run_id


def create_graph(model, prompt, tools, saver):
    backend = StateBackend()
    return create_deep_agent(
        model=model, system_prompt=prompt, tools=tools, backend=backend,
        middleware=[
            FilesystemMiddleware(backend=backend, tools=["ls", "read_file", "write_file", "edit_file", "glob", "grep"]),
            CompletedContextMiddleware(),
            SummarizationMiddleware(model=model, backend=backend, trigger=("tokens", 16000), keep=("tokens", 6000)),
            TodoListMiddleware(), NoProgressMiddleware(), ToolRequestMiddleware(),
            ModelCallLimitMiddleware(run_limit=MODEL_CALLS_PER_RUN, exit_behavior="error"),
        ], checkpointer=saver,
    )


def append_messages(messages, state):
    """Keep completed turns even on cancellation/failure; no duplicate replay."""
    seen = {m.get("agent_message_id") for m in messages if m.get("agent_message_id")}
    items = state.get("messages", [])
    # Do not persist a tool-call message before all its results are available.
    results = {m.tool_call_id for m in items if isinstance(m, ToolMessage)}
    pending = {c["id"] for m in items if isinstance(m, AIMessage) and any(c["id"] not in results for c in m.tool_calls) for c in m.tool_calls}
    for message in items:
        if not isinstance(message, (AIMessage, ToolMessage)) or not message.id or message.id.startswith("seed-") or message.id in seen:
            continue
        if isinstance(message, AIMessage) and any(call["id"] in pending for call in message.tool_calls):
            continue
        if isinstance(message, ToolMessage) and message.tool_call_id in pending:
            continue
        item = convert_to_openai_messages(message)
        item["agent_message_id"] = message.id
        messages.append(item)
        seen.add(message.id)


async def respond(messages, chat_id, prompt, initial, provider, model, connection, repair_session=None):
    from service.chat import ai_chat

    repair = repair_session.report if repair_session else None
    from service.chat.agent_policy import task_anchor
    prompt += task_anchor(messages, repair)
    run_id = run_identity(messages, chat_id, provider, model, connection, repair)
    if run_id in _active_runs or (chat_id and chat_id in _active_chats):
        raise ValueError(t("当前对话正在生成，请等待完成"))
    from service.chat import agent_usage
    usage_scope = agent_usage.current_run.set(run_id)
    _active_runs.add(run_id)
    if chat_id:
        _active_chats.add(chat_id)
    try:
        user = next(m for m in reversed(messages) if m.get("role") == "user")
        if user.get("agent_output_truncated"):
            prompt += " Previous response was truncated and its tool calls were not executed. Do not emit the whole file again. Write a small initial virtual draft, then extend it using multiple edit_file calls; deliver_draft reads the complete draft locally."
        if chat_id:
            ai_chat.save_chat(chat_id, messages)  # Persist retry identity before calling the model.
        from service.chat.task_workflow import TaskWorkflow
        workflow = TaskWorkflow(chat_id, run_id, 'main' if chat_id else 'analysis')
        agent_store.register(run_id, chat_id)
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 600}
        path = agent_store.root() / "checkpoints.sqlite"
        # Disable tracing regardless of inherited environment settings. Model
        # credentials live only in a private model field, outside graph state.
        with tracing_context(enabled=False):
            async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
                await saver.setup()
                if os.name != "nt":
                    path.chmod(0o600)
                graph = create_graph(CalabashChatModel(provider, model, connection, chat_id=chat_id), prompt,
                                     build_tools(chat_id, messages, run_id, repair_session, model_identity=hashlib.sha256(json.dumps((provider, model, connection), sort_keys=True).encode()).hexdigest(), workflow=workflow), saver)
                state = await graph.aget_state(config)
                if state.values:
                    # Resume only pending graph work. A completed run is replayed
                    # to the UI without executing another model or tool call.
                    value = None
                    append_messages(messages, state.values)
                    yield "activity", "resuming"
                else:
                    if initial is None:
                        from service.chat.chat_context import prepare
                        initial = prepare(messages, chat_id, include_reasoning=False)
                        if chat_id:
                            from service.files.chat_images import attach_references
                            initial = attach_references(initial, chat_id)
                    seed = convert_to_messages(initial)
                    for index, message in enumerate(seed):
                        message.id = f"seed-{index}"
                    value = {"messages": seed}
                    # A follow-up user message starts fresh execution, but keeps
                    # its own conversation's virtual drafts. It never resumes
                    # another turn's pending side effects automatically.
                    if not repair_session:
                        previous_user = next((m for m in reversed(messages)
                                         if m.get("role") == "user" and m.get("agent_checkpoint_id") != run_id
                                         and m.get("agent_checkpoint_id")), {})
                        # Redacted repair drafts are never inherited by an
                        # unrestricted turn: they must be read/redacted afresh.
                        previous = None if previous_user.get("agent_repair") else previous_user.get("agent_checkpoint_id")
                        if previous and agent_store.owned(previous, chat_id):
                            previous_state = await graph.aget_state({"configurable": {"thread_id": previous}})
                            if previous_state.values.get("files"):
                                value["files"] = previous_state.values["files"]
                succeeded = False
                prior_messages = state.values.get('messages', []) if state.values else value.get('messages', [])
                reported_tools = {message.id for message in prior_messages if isinstance(message, ToolMessage)}
                try:
                    async for mode, event in graph.astream(value, config, stream_mode=["messages", "custom", "updates"]):
                        if mode == "messages":
                            chunk, metadata = event
                            # Summarization is internal context maintenance.
                            if metadata.get("langgraph_node") != "model" or metadata.get("lc_source") == "summarization":
                                continue
                            if isinstance(chunk.content, str) and chunk.content:
                                yield "text", chunk.content
                            if getattr(chunk, "tool_call_chunks", None):
                                yield "activity", "generating_tool"
                        elif mode == "custom" and isinstance(event, dict) and "kind" in event:
                            yield event["kind"], event["value"]
                        elif mode == "updates":
                            current = await graph.aget_state(config)
                            for message in current.values.get('messages', []):
                                if isinstance(message, ToolMessage) and message.id not in reported_tools:
                                    reported_tools.add(message.id)
                                    yield 'activity', message.name or 'tool'
                            append_messages(messages, current.values)
                    succeeded = True
                except GraphRecursionError as error:
                    raise PublicAgentError(t("本轮执行预算已用完，进度已保存；点击继续生成")) from error
                except Exception as error:
                    from langchain.agents.middleware.model_call_limit import (
                        ModelCallLimitExceededError,
                    )
                    if isinstance(error, ModelCallLimitExceededError):
                        raise PublicAgentError(t("本轮执行预算已用完，进度已保存；点击继续生成")) from error
                    if isinstance(error, OutputLimitError):
                        user["agent_output_truncated"] = True
                    raise
                finally:
                    current = await graph.aget_state(config)
                    append_messages(messages, current.values)
                    workflow.finish(succeeded)
                    if succeeded:
                        user["agent_completed"] = True
                    if chat_id and ai_chat.chat_exists(chat_id):
                        ai_chat.save_chat(chat_id, messages)
    finally:
        agent_usage.current_run.reset(usage_scope)
        _active_runs.discard(run_id)
        if chat_id:
            _active_chats.discard(chat_id)
        if chat_id and not ai_chat.chat_exists(chat_id):
            agent_store.delete_chat(chat_id)
