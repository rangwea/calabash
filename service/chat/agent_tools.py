"""Bridge virtual drafts to the existing Calabash tool and repair services."""

import hashlib
import json

from deepagents.backends import StateBackend
from deepagents.backends.utils import file_data_to_string
from langchain.tools import ToolRuntime, tool
from langchain_core.tools import StructuredTool

from service.chat import agent_store

SIDE_EFFECTS = {"write_tool", "preview_tool"}
REPAIR_ACCESS_TOOLS = {"read_tool", "write_tool", "validate_tool", "preview_tool", "read_tool_logs"}


def build_tools(chat_id, messages, run_id, repair_session=None):
    from service.chat import ai_chat

    async def dispatch(name, parameters, runtime):
        runtime.stream_writer({"kind": "activity", "value": name})
        if chat_id and not ai_chat.chat_exists(chat_id):
            raise ValueError("Conversation was deleted")
        call_id = runtime.tool_call_id
        digest = hashlib.sha256(json.dumps([name, parameters], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if name in SIDE_EFFECTS:
            receipt = agent_store.begin(run_id, call_id, digest)
            if receipt is not None:
                emit_result(name, receipt, runtime)
                return receipt
        try:
            result = repair_session.execute(name, parameters) if repair_session and name in REPAIR_ACCESS_TOOLS else await ai_chat.execute_chat_tool(name, parameters, chat_id, messages)
        except Exception as error:  # noqa: BLE001 - never pass arbitrary repair exception text to the model.
            result = {"error": type(error).__name__}
            from service.tools.tool_runtime import ToolEntryPointError
            if isinstance(error, (ToolEntryPointError, SyntaxError)):
                from service.tools.component_api import validation_diagnosis
                result['diagnosis'] = validation_diagnosis(parameters.get('content', ''))
                result['executed'] = False
        if name in SIDE_EFFECTS:
            agent_store.finish(run_id, call_id, result)
        emit_result(name, result, runtime)
        return result

    def emit_result(name, result, runtime):
        if not isinstance(result, dict):
            return
        if result.get("requires_manual_run"):
            runtime.stream_writer({"kind": "manual_preview", "value": result})
        elif name == "preview_tool" and result.get("success"):
            runtime.stream_writer({"kind": "preview", "value": result})

    def wrap(schema):
        definition = schema["function"]

        async def execute(runtime: ToolRuntime, **parameters):
            return json.dumps(await dispatch(definition["name"], parameters, runtime), ensure_ascii=False)

        return StructuredTool.from_function(
            coroutine=execute, name=definition["name"], description=definition["description"],
            args_schema={**definition["parameters"], "additionalProperties": False},
        )

    result = [wrap(schema) for schema in ai_chat.schemas()
              if repair_session or schema['function']['name'] != 'read_tool_logs']

    @tool
    async def stage_tool(project: str, name: str, runtime: ToolRuntime) -> str:
        """Read an existing authorized tool into a virtual draft for incremental editing. Returns file_path and revision. Never executes code."""
        data = await dispatch("read_tool", {"project": project, "name": name}, runtime)
        if not isinstance(data, dict) or "content" not in data:
            return json.dumps(data, ensure_ascii=False)
        # Validate identity even for the virtual path.
        ai_chat.tool_path(project, name)
        path = f"/drafts/{project}/{name}.py"
        StateBackend().write(path, data["content"])
        return json.dumps({"file_path": path, "revision": data["revision"]})

    @tool
    async def deliver_draft(project: str, name: str, file_path: str, action: str, runtime: ToolRuntime, revision: str = "") -> str:
        """Validate, preview or save a complete virtual draft without emitting its code again. action is validate_tool, preview_tool or write_tool. Existing writes require the revision from stage_tool/read_tool. Preview does not publish."""
        if action not in {"validate_tool", "preview_tool", "write_tool"}:
            return json.dumps({"error": "Unsupported draft action"})
        data = runtime.state.get("files", {}).get(file_path)
        if data is None:
            return json.dumps({"error": "Virtual draft not found"})
        content = file_data_to_string(data)
        if len(content) > 1_000_000:
            return json.dumps({"error": "Draft is too large"})
        return json.dumps(await dispatch(action, {"project": project, "name": name, "content": content, "revision": revision}, runtime), ensure_ascii=False)

    return [*result, stage_tool, deliver_draft]
