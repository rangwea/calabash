"""
本地工具预览与调试 API。

工具管理由 Agent / CLI 直接操作本地文件，不提供 HTTP 管理接口。
- GET    /api/tools/preview/list       列出所有预览工具
- GET    /api/tools/preview/log/{key}  查看预览工具日志
- POST   /api/tools/preview            临时预览工具
- POST   /api/tools/preview/{username}/{tool_name} 固定预览工具
"""

import asyncio
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from service.tools.preview_service import (
    create_fixed_preview,
    create_temporary_preview,
    fixed_preview_key_from_path,
    get_fixed_preview_log_url,
    get_preview_log_file,
    get_preview_log_url,
    list_previews,
    read_preview_code,
    validate_preview_key,
)

router = APIRouter(prefix="/api/tools", tags=["tools"])


# ============================================================================
# 请求/响应模型
# ============================================================================


class ToolContentRequest(BaseModel):
    """工具内容请求体"""

    content: str = Field(..., description="工具 Python 代码")


class PreviewResponse(BaseModel):
    """预览响应"""

    url: str
    message: str
    key: str | None = None
    preview_url: str | None = None
    log_url: str | None = None


# ============================================================================
# API 路由
# ============================================================================


@router.get("/preview/list")
async def list_preview_tools():
    """
    列出所有预览工具

    返回所有临时目录中的预览工具信息，包括 key、文件大小、日志状态等。
    """
    tools = list_previews()
    return {"tools": tools, "total": len(tools)}


@router.get("/preview/log/fixed/{username}/{tool_name}")
async def get_fixed_preview_log(
    username: str,
    tool_name: str,
    lines: Annotated[int, Query(ge=1, le=10000, description="返回最后N行")] = 100,
):
    preview_key = fixed_preview_key_from_path(username, tool_name)
    return await _get_preview_log_by_key(preview_key, lines)


@router.get("/preview/log/{preview_key}")
async def get_preview_log(
    preview_key: str,
    lines: Annotated[int, Query(ge=1, le=10000, description="返回最后N行")] = 100,
):
    """
    获取预览工具日志内容

    - **preview_key**: 预览工具 key
    - **lines**: 返回最后N行（默认100）
    """
    safe_key = validate_preview_key(preview_key)
    if safe_key is None:
        return PlainTextResponse(content="预览 key 不合法", status_code=400)
    return await _get_preview_log_by_key(safe_key, lines)


async def _get_preview_log_by_key(preview_key: str, lines: int):
    log_file = get_preview_log_file(preview_key)
    if log_file is None or not os.path.exists(log_file):
        return PlainTextResponse(
            content=f"日志文件不存在: {preview_key}",
            status_code=404,
        )

    try:
        text = await asyncio.to_thread(Path(log_file).read_text, encoding="utf-8")
        all_lines = text.splitlines(keepends=True)

        # 返回最后 N 行
        tail_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
        content = "".join(tail_lines)
        return PlainTextResponse(content=content)
    except OSError as e:
        return PlainTextResponse(
            content=f"读取日志失败: {e}",
            status_code=500,
        )


@router.get("/preview/code/fixed/{username}/{tool_name}")
async def get_fixed_preview_code(username: str, tool_name: str):
    preview_key = fixed_preview_key_from_path(username, tool_name)
    return await _get_preview_code_by_key(preview_key)


@router.get("/preview/code/{preview_key}")
async def get_preview_code(preview_key: str):
    """
    获取预览工具代码内容

    - **preview_key**: 预览工具 key
    """
    safe_key = validate_preview_key(preview_key)
    if safe_key is None:
        return PlainTextResponse(content="预览 key 不合法", status_code=400)
    return await _get_preview_code_by_key(safe_key)


async def _get_preview_code_by_key(preview_key: str):
    try:
        content = await asyncio.to_thread(read_preview_code, preview_key)
    except OSError as e:
        return PlainTextResponse(
            content=f"读取代码失败: {e}",
            status_code=500,
        )

    if content is None:
        return PlainTextResponse(
            content=f"预览工具不存在: {preview_key}",
            status_code=404,
        )

    return PlainTextResponse(content=content)


@router.post("/preview", response_model=PreviewResponse)
async def preview_tool(body: ToolContentRequest):
    """
    临时预览工具

    上传代码后返回预览 URL，代码保存在临时目录，不会持久化。
    """
    data = create_temporary_preview(body.content)
    if not data["success"]:
        return JSONResponse(status_code=data.get("status_code", 400), content=data)

    return PreviewResponse(
        url=data["url"],
        message=data["message"],
        key=data.get("key"),
        preview_url=data.get("preview_url") or data.get("url"),
        log_url=data.get("log_url")
        or (get_preview_log_url(data["key"]) if data.get("key") else None),
    )


@router.post("/preview/{username}/{tool_name}", response_model=PreviewResponse)
async def preview_fixed_tool(username: str, tool_name: str, body: ToolContentRequest):
    """
    固定预览工具

    同一个 username/tool_name 始终覆盖同一个预览文件，因此浏览器中的预览链接
    可以保持不变，编辑代码后刷新页面即可看到最新内容。
    """
    if not username.strip() or not tool_name.strip():
        return JSONResponse(
            status_code=400,
            content={"detail": "username 和 tool_name 不能为空"},
        )

    result = create_fixed_preview(username, tool_name, body.content)
    if not result["success"]:
        return JSONResponse(
            status_code=result["status_code"],
            content={
                "success": False,
                "code": result.get("code", "preview_failed"),
                "message": result.get("message") or result.get("error", "预览失败"),
                "next_action": result.get("next_action", "inspect_error"),
                **{
                    key: result[key]
                    for key in ("line", "column")
                    if result.get(key) is not None
                },
            },
        )

    return PreviewResponse(
        url=result["url"],
        message=result["message"],
        key=result["key"],
        preview_url=result.get("preview_url") or result["url"],
        log_url=get_fixed_preview_log_url(username, tool_name),
    )
