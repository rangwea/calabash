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
    from service.chat.code_target import CodeTarget
    targets = CodeTarget(run_id, chat_id)

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
            if repair_session and name in REPAIR_ACCESS_TOOLS:
                result = repair_session.execute(name, parameters)
            else:
                result = targets.execute(name, parameters) if name in REPAIR_ACCESS_TOOLS - {'read_tool_logs'} else None
                if result is None:
                    result = await ai_chat.execute_chat_tool(name, parameters, chat_id, messages)
                    if name == 'read_tool' and isinstance(result, dict):
                        result['source'] = 'published'
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
        return json.dumps({"file_path": path, "revision": data["revision"], "source": data.get("source", "preview" if repair_session and repair_session.report.get("preview_key") else "published")})

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

    async def inspect(operation, project, name, file_path, runtime, **options):
        from service.chat.code_inspection import inspect_source
        if file_path:
            data = runtime.state.get('files', {}).get(file_path)
            if data is None:
                return json.dumps({'error': 'Virtual draft not found'})
            content, source = file_data_to_string(data), 'draft'
        else:
            data = await dispatch('read_tool', {'project': project, 'name': name}, runtime)
            if not isinstance(data, dict) or 'content' not in data:
                return json.dumps(data, ensure_ascii=False)
            content, source = data['content'], data.get('source', 'preview' if repair_session and repair_session.report.get('preview_key') else 'published')
        return json.dumps({**inspect_source(content, operation, **options), 'source': source}, ensure_ascii=False)

    @tool
    async def outline_code(project: str, name: str, runtime: ToolRuntime, file_path: str = '', offset: int = 0, limit: int = 80) -> str:
        """List qualified Python functions/classes and line ranges without execution. file_path optionally selects this conversation's virtual draft; otherwise read the bound tool source."""
        return await inspect('outline_code', project, name, file_path, runtime, offset=offset, limit=limit)

    @tool
    async def read_code_symbol(project: str, name: str, symbol: str, runtime: ToolRuntime, file_path: str = '', offset: int = 0, limit: int = 80) -> str:
        """Read one qualified symbol from outline_code, at most 120 lines/16000 characters. Includes source identity and revision. Never executes code."""
        return await inspect('read_code_symbol', project, name, file_path, runtime, symbol=symbol, offset=offset, limit=limit)

    @tool
    async def search_code(project: str, name: str, query: str, runtime: ToolRuntime, file_path: str = '', offset: int = 0, limit: int = 30) -> str:
        """Find literal text with line numbers in the bound source or a conversation virtual draft. query max 200 characters, limit max 120. Not regex or shell."""
        return await inspect('search_code', project, name, file_path, runtime, query=query, offset=offset, limit=limit)

    return [*result, stage_tool, deliver_draft, outline_code, read_code_symbol, search_code]
