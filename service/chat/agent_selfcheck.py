"""Offline frozen-runtime check, using a real temporary file and a scripted model."""

import asyncio
import tempfile
from pathlib import Path

from langchain.tools import tool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langsmith import tracing_context


class SelfCheckModel(BaseChatModel):
    model_name: str = "calabash:local"

    @property
    def _llm_type(self):
        return "calabash-selfcheck"

    def bind_tools(self, tools, **kwargs):
        names = {t.name for t in tools}
        if names & {"execute", "task", "read_file", "write_file", "edit_file", "stage_tool", "deliver_draft"}:
            raise ValueError("Unexpected privileged tools")
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(message, ToolMessage) for message in messages):
            message = AIMessage(content="Synthetic check completed")
        else:
            message = AIMessage(content="", tool_calls=[{"name": "write_tool_file", "args": {"content": "def main():\n    pass\n"}, "id": "synthetic-draft", "type": "tool_call"}])
        return ChatResult(generations=[ChatGeneration(message=message)])


async def _check(path):
    from service.chat.agent_runtime import create_graph
    config = {"configurable": {"thread_id": "selfcheck"}}
    source = path.parent / 'source.py'
    @tool
    def write_tool_file(content: str) -> str:
        """Save one selfcheck source file in its host-selected temporary directory."""
        source.write_text(content)
        return '{"success":true}'

    with tracing_context(enabled=False):
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            graph = create_graph(SelfCheckModel(), "Offline synthetic check", [write_tool_file], saver)
            result = await graph.ainvoke({"messages": [{"role": "user", "content": "Create a real working draft"}]}, config)
            if "def main" not in source.read_text() or result.get("files"):
                raise ValueError("Real working source missing")
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            graph = create_graph(SelfCheckModel(), "Offline synthetic check", [write_tool_file], saver)
            state = await graph.aget_state(config)
            if state.next or not state.values.get("messages") or state.values.get("files"):
                raise ValueError("Checkpoint roundtrip failed")


def check_runtime():
    with tempfile.TemporaryDirectory(prefix="calabash-agent-check-") as temporary:
        asyncio.run(_check(Path(temporary) / "checkpoints.sqlite"))
