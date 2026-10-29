"""Official model connections and protocol adaptation."""

import json
import os
from urllib.parse import urlparse

import httpx

from core.i18n import t
from core.local_paths import app_dir

PROVIDERS = {
    "deepseek": ("DeepSeek", "https://api.deepseek.com"),
    "openai": ("OpenAI", "https://api.openai.com/v1"),
    "anthropic": ("Anthropic", "https://api.anthropic.com/v1"),
    "qwen": ("通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
}


def load():
    path = app_dir() / "model_connections.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"selected": None, "connections": {}}


def save(data):
    app_dir().mkdir(parents=True, exist_ok=True)
    path = app_dir() / "model_connections.json"
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(data, file, ensure_ascii=False)
    temporary.chmod(0o600)
    temporary.replace(path)


def options():
    return {f"{provider}::{model}": model for provider, connection in load()["connections"].items() if connection.get("key") for model in connection.get("models", [])}


def selected():
    data = load()
    available = options()
    return data["selected"] if data["selected"] in available else next(iter(available), None)


def select(value):
    if value not in options():
        raise ValueError(t("模型尚未配置"))
    data = load()
    data["selected"] = value
    save(data)


def active():
    value = selected()
    if not value:
        raise ValueError(t("请在设置中配置模型连接"))
    provider, model = value.split("::", 1)
    return provider, model, load()["connections"][provider]


async def available_models(provider, connection):
    base = connection["base_url"].strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(t("请填写有效的 HTTPS API 地址"))
    headers = {"x-api-key": connection["key"], "anthropic-version": "2023-06-01"} if provider == "anthropic" else {"Authorization": f"Bearer {connection['key']}"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(base + "/models", headers=headers)
        if response.status_code != 200:
            raise ValueError(t("连接验证失败（{status}），请检查密钥和 API 地址", status=response.status_code))
        try:
            data = response.json()["data"]
            ids = sorted({item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]})
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(t("服务未返回有效模型列表")) from error
    if not ids:
        raise ValueError(t("服务未返回有效模型列表"))
    return ids


async def validate_connection(provider, connection):
    ids = await available_models(provider, connection)
    missing = [model for model in connection["models"] if model not in ids]
    if missing:
        raise ValueError(t("模型 ID 不可用：{models}。请点击获取模型重新选择", models=", ".join(missing)))
    return ids


def request(provider, model, connection, messages, tools):
    # Conversation IDs and file references are local metadata, not model input.
    allowed = {"role", "content", "tool_calls", "tool_call_id", "name"}
    # Requests below explicitly disable DeepSeek thinking; hidden reasoning from
    # earlier attempts is not input for this non-thinking authoring mode.
    messages = [{key: value for key, value in message.items() if key in allowed} for message in messages]
    base = connection["base_url"].rstrip("/")
    if provider != "anthropic":
        payload = {"model": model, "messages": messages, "tools": tools, "stream": True}
        if provider == "deepseek":
            # Tool authoring uses non-thinking mode explicitly. Provider defaults
            # can otherwise spend the request entirely on hidden reasoning.
            payload["thinking"] = {"type": "disabled"}
            if model in {"deepseek-flash", "deepseek-v4-pro"}:
                payload["max_tokens"] = 32768
        return base + "/chat/completions", {"Authorization": f"Bearer {connection['key']}"}, payload
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    converted = []
    for message in messages:
        if message["role"] == "system":
            continue
        role = "user" if message["role"] == "tool" else message["role"]
        if message["role"] == "tool":
            content = [{"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": message["content"]}]
        else:
            content = [{"type": "text", "text": message["content"]}] if message.get("content") else []
            content += [{"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": json.loads(call["function"]["arguments"])} for call in message.get("tool_calls", [])]
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"].extend(content)
        else:
            converted.append({"role": role, "content": content})
    definitions = [{"name": t["function"]["name"], "description": t["function"]["description"], "input_schema": t["function"]["parameters"]} for t in tools]
    return base + "/messages", {"x-api-key": connection["key"], "anthropic-version": "2023-06-01"}, {"model": model, "system": system, "messages": converted, "tools": definitions, "max_tokens": 8192, "stream": True}


def normalize(packet, provider):
    if provider != "anthropic":
        return packet
    delta = {}
    if packet.get("type") == "content_block_start":
        block = packet["content_block"]
        if block["type"] == "tool_use":
            delta = {"tool_calls": [{"index": packet["index"], "id": block["id"], "function": {"name": block["name"], "arguments": ""}}]}
        elif block["type"] == "text":
            delta = {"content": block.get("text", "")}
    elif packet.get("type") == "content_block_delta":
        value = packet["delta"]
        if value["type"] == "text_delta":
            delta = {"content": value["text"]}
        elif value["type"] == "input_json_delta":
            delta = {"tool_calls": [{"index": packet["index"], "function": {"arguments": value["partial_json"]}}]}
    elif packet.get("type") == "message_delta":
        reason = packet.get("delta", {}).get("stop_reason")
        return {"choices": [{"delta": {}, "finish_reason": {"max_tokens": "length", "tool_use": "tool_calls", "end_turn": "stop"}.get(reason, reason)}]}
    elif packet.get("type") == "message_stop":
        return {"choices": [{"delta": {}, "finish_reason": "stop"}]}
    return {"choices": [{"delta": delta}], **({"error": packet["error"]} if "error" in packet else {})}
