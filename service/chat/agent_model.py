"""Deep Agents model adapter over Calabash's existing provider protocols."""

import asyncio
import json
import sqlite3
import time
from uuid import uuid4

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessageChunk,
    convert_to_openai_messages,
    message_chunk_to_message,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import PrivateAttr

from core.i18n import t
from service.chat import model_providers


class PublicAgentError(ValueError):
    """A host-authored message safe to display without provider payloads."""


class OutputLimitError(PublicAgentError):
    """No tool calls from a truncated response may be executed."""


class CalabashChatModel(BaseChatModel):
    # Framework profiles use our own namespace, independently of the provider.
    model_name: str = "calabash:local"
    _provider: str = PrivateAttr()
    _model: str = PrivateAttr()
    _connection: dict = PrivateAttr()
    _chat_id: str | None = PrivateAttr(default=None)
    _tools: list = PrivateAttr(default_factory=list)

    def __init__(self, provider, model, connection, *, chat_id=None):
        super().__init__(cache=False)
        self._provider, self._model, self._connection = provider, model, dict(connection)
        self._chat_id = chat_id

    @property
    def _llm_type(self):
        return "calabash"

    def bind_tools(self, tools, **kwargs):
        bound = self.model_copy()
        bound._tools = [convert_to_openai_tool(tool) for tool in tools]
        return bound

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("Calabash models require asynchronous execution")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        combined = None
        async for chunk in self._astream(messages, stop, run_manager, **kwargs):
            combined = chunk if combined is None else combined + chunk
        return ChatResult(generations=[ChatGeneration(message=message_chunk_to_message(combined.message))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        from service.chat import agent_usage
        observation = {'usage': {}, 'first_token_ms': None}
        started = time.monotonic()
        observation['started'] = started
        status = 'failed'
        try:
            async for chunk in self._stream_request(messages, stop, run_manager, observation=observation, **kwargs):
                if observation['first_token_ms'] is None:
                    observation['first_token_ms'] = int((time.monotonic() - started) * 1000)
                yield chunk
            status = 'completed'
        except asyncio.CancelledError:
            status = 'cancelled'
            raise
        finally:
            from langchain_core.runnables.config import ensure_config
            metadata = {**ensure_config().get('metadata', {}), **(getattr(run_manager, 'metadata', None) or {})}
            try:
                from service.chat import agent_store
                run_id = agent_usage.current_run.get()
                if run_id and self._chat_id and not agent_store.owned(run_id, self._chat_id):
                    run_id = None  # Deleted chats must not recreate usage rows after an in-flight request.
                agent_usage.record(uuid4().hex, run_id,
                    'summary' if metadata.get('lc_source') == 'summarization' else 'model',
                    self._provider, self._model, status, int((time.monotonic() - started) * 1000),
                    observation['first_token_ms'], observation['usage'])
            except (OSError, sqlite3.Error):
                from core.logger import get_logger
                get_logger(__name__).warning('Local agent usage recording unavailable')

    async def _stream_request(self, messages, stop=None, run_manager=None, *, observation, **kwargs):
        from service.chat.ai_chat import MODEL_REQUEST_TIMEOUT

        wire = convert_to_openai_messages(messages)
        from service.files.chat_images import hydrate
        if any(isinstance(message.get('content'), list) and any(block.get('type') == 'image_url' for block in message['content']) for message in wire):
            wire = await asyncio.to_thread(hydrate, wire, self._chat_id, self._provider, self._model, self._connection)
        url, headers, payload = model_providers.request(
            self._provider, self._model, self._connection, wire, self._tools,
        )
        # Calls are deliberately buffered until the whole response is complete.
        # Streaming incomplete JSON into the graph risks dispatching partial writes.
        calls, text, finish, done = {}, "", None, False
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client,
            asyncio.timeout(MODEL_REQUEST_TIMEOUT),
            client.stream('POST', url, headers=headers, json=payload) as response,
        ):
            if response.status_code != 200:
                from core.logger import get_logger
                get_logger(__name__).warning('Model request rejected: provider={} status={}', self._provider, response.status_code)
                if response.status_code == 400:
                    raise PublicAgentError(t("模型暂时无法处理这次请求，请更换模型或新建对话后重试"))
                raise PublicAgentError(t("模型服务暂时无法使用，请检查连接设置和账户余额后重试"))
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    done = True
                    break
                raw_packet = json.loads(data)
                from service.chat.agent_usage import observe
                observe(raw_packet, observation['usage'])
                packet = model_providers.normalize(raw_packet, self._provider)
                if packet.get("error"):
                    raise PublicAgentError(t("模型服务返回错误，请稍后重试"))
                for choice in packet.get("choices", []):
                    if observation['first_token_ms'] is None and (choice.get('delta', {}).get('content') or choice.get('delta', {}).get('tool_calls')):
                        observation['first_token_ms'] = int((time.monotonic() - observation['started']) * 1000)
                    # Anthropic emits message_stop after max_tokens. A later
                    # generic stop must not turn truncation into success.
                    if finish != "length":
                        finish = choice.get("finish_reason") or finish
                    delta = choice.get("delta", {})
                    token = delta.get("content") or ""
                    if token:
                        text += token
                        yield ChatGenerationChunk(message=AIMessageChunk(content=token))
                    for call in delta.get("tool_calls", []):
                        item = calls.setdefault(call["index"], {"id": "", "name": "", "args": ""})
                        item["id"] += call.get("id", "")
                        item["name"] += call.get("function", {}).get("name", "")
                        item["args"] += call.get("function", {}).get("arguments", "")
        if not done and not finish:
            raise PublicAgentError(t("模型响应中断，进度已保存；请继续生成"))
        if finish == "length":
            raise OutputLimitError(t("模型输出达到长度限制，未执行残缺调用；请继续生成，代码可分段编辑"))
        if finish in {"content_filter", "refusal"}:
            raise PublicAgentError(t("模型未返回可用内容，请重试或选择其他模型"))
        parsed = []
        for index, call in calls.items():
            try:
                args = json.loads(call["args"] or "{}")
            except ValueError as error:
                raise OutputLimitError(t("模型输出达到长度限制，未执行残缺调用；请继续生成，代码可分段编辑")) from error
            if not isinstance(args, dict) or not call["name"]:
                raise PublicAgentError(t("模型未返回可用内容，请重试或选择其他模型"))
            parsed.append({"index": index, "id": call["id"] or uuid4().hex, "name": call["name"], "args": json.dumps(args, ensure_ascii=False)})
        if not parsed and not text.strip():
            raise PublicAgentError(t("模型未返回可用内容，请重试或选择其他模型"))
        yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=parsed))
