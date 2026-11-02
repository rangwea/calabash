"""Single-agent execution, local checkpoints and the desktop streaming contract."""

import hashlib
import json
import os
from uuid import uuid4

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, create_deep_agent, register_harness_profile
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware import ModelCallLimitMiddleware, TodoListMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, convert_to_messages, convert_to_openai_messages
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import GraphRecursionError
from langsmith import tracing_context

from core.i18n import t
from service.chat import agent_store
from service.chat.agent_model import CalabashChatModel, OutputLimitError
from service.chat.agent_tools import build_tools

MODEL_CALLS_PER_RUN = 40
_active_runs = set()
_active_chats = set()

# Explicitly remove delegation. Filesystem tools below operate only on graph
# state; there is no local filesystem or shell backend.
register_harness_profile("calabash:local", HarnessProfile(
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
))


class NoProgressMiddleware(AgentMiddleware):
    async def abefore_model(self, state, runtime):
        calls = []
        for message in state["messages"]:
            if isinstance(message, HumanMessage):
                calls = []
            elif isinstance(message, AIMessage) and message.tool_calls:
                calls.append(message)
        if len(calls) >= 4:
            signatures = [json.dumps([(c["name"], c["args"]) for c in message.tool_calls], sort_keys=True) for message in calls[-4:]]
            if len(set(signatures)) == 1:
                raise ValueError(t("检测到重复操作，已暂停；请补充要求后继续"))


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
            SummarizationMiddleware(model=model, backend=backend, trigger=("tokens", 16000), keep=("tokens", 6000)),
            TodoListMiddleware(), NoProgressMiddleware(),
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
                                     build_tools(chat_id, messages, run_id, repair_session), saver)
                state = await graph.aget_state(config)
                if state.values:
                    # Resume only pending graph work. A completed run is replayed
                    # to the UI without executing another model or tool call.
                    value = None
                    append_messages(messages, state.values)
                    yield "activity", "resuming"
                else:
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
                            append_messages(messages, current.values)
                    succeeded = True
                except GraphRecursionError as error:
                    raise ValueError(t("本轮执行预算已用完，进度已保存；点击继续生成")) from error
                except Exception as error:
                    from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
                    if isinstance(error, ModelCallLimitExceededError):
                        raise ValueError(t("本轮执行预算已用完，进度已保存；点击继续生成")) from error
                    if isinstance(error, OutputLimitError):
                        user["agent_output_truncated"] = True
                    raise
                finally:
                    current = await graph.aget_state(config)
                    append_messages(messages, current.values)
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
