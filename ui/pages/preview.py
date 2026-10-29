"""
工具预览路由

POST /api/tools/preview 会把代码写入 `_TMP_DIR/{token}.py` 并返回
`/{mount_path}/preview/{token}` 这个 URL。

POST /api/tools/preview/{username}/{tool_name} 会覆盖同一个固定预览文件，
并返回 `/{mount_path}/preview/{username}/{tool_name}`，便于一边编辑
一边刷新同一个预览页面。
"""

import os

from nicegui import ui

from component.tool_capabilities import render_capability_gate
from component.tool_repair import RepairFeedback
from component.tool_shell import render_tool_shell
from core.i18n import t
from core.logger import get_logger
from core import tool_run_logs
from service.tools.preview_service import (
    fixed_preview_key_from_path,
    get_preview_file,
    validate_preview_key,
)
from service.capabilities.tool_capabilities import ToolCapabilityError
from service.tools.tool_runtime import load_tool_entrypoint

logger = get_logger(__name__)


def _render_error(title: str, message: str, detail: str | None = None) -> None:
    """渲染统一风格的错误提示页面"""
    with ui.column().classes("items-center justify-center min-h-screen gap-4"):
        ui.icon("error_outline", size="4rem").classes("text-red-500")
        ui.label(t(title)).classes("text-2xl font-bold text-red-600")
        ui.label(t(message)).classes("text-gray-600 text-center max-w-md")
        if detail:
            ui.label(detail).classes("text-xs text-gray-400 mt-2 max-w-md break-all")


@ui.page("/preview/{token}")
async def preview_handler(
    token: str, embedded: bool = False, context: str | None = None
) -> None:
    """临时工具预览页面

    从预览目录加载临时上传的工具代码并执行。
    """
    preview_key = validate_preview_key(token)
    if preview_key is None:
        _render_error("预览地址无效", "预览 key 包含不支持的字符。", f"key: {token}")
        return
    await _render_preview(
        preview_key=preview_key,
        subtitle=f"token {token[:16]}...",
        embedded=embedded,
        context=context,
    )


@ui.page("/preview/{username}/{tool_name}")
async def fixed_preview_handler(
    username: str, tool_name: str, embedded: bool = False, context: str | None = None
) -> None:
    """固定工具预览页面"""
    preview_key = fixed_preview_key_from_path(username, tool_name)
    await _render_preview(
        preview_key=preview_key,
        subtitle=f"{username}/{tool_name}",
        embedded=embedded,
        context=context,
    )


async def _render_preview(
    preview_key: str, subtitle: str, embedded: bool = False, context: str | None = None
) -> None:
    ui.context.client.calabash_output_owner = (f"preview:{preview_key}", None)
    if context:
        from service.files import tool_inputs

        try:
            tool_inputs.resolve(context, preview_key)
            ui.context.client.calabash_output_owner = tool_inputs.owner(
                context, preview_key
            )
        except ValueError:
            _render_error(
                "文件引用已失效", "请回到对话重新生成预览，或在工具中重新选择文件。"
            )
            return
        ui.context.client.calabash_input_context = (context, preview_key)
    owner, _ = ui.context.client.calabash_output_owner
    if context and owner.startswith('tool:'):
        project, name = owner.removeprefix('tool:').split('/', 1)
    else:
        project, name = '_previews', preview_key
    run = tool_run_logs.start(project, name, preview_key=preview_key, client=ui.context.client)
    preview_logger = run.logger
    preview_logger.info('Rendering preview run')

    filepath = get_preview_file(preview_key)

    if not os.path.exists(filepath):
        preview_logger.warning(f"预览文件不存在: {filepath}")
        _render_error(
            "预览已过期",
            "预览链接对应的文件不存在或已被清理，请重新生成预览。",
            f"key: {preview_key}",
        )
        return

    module_name = f"preview_{preview_key.replace('-', '_').replace('.', '_')}_{run.id}"
    run.attach_module(module_name)
    feedback = None
    owner, _ = ui.context.client.calabash_output_owner
    if context and owner.startswith("tool:"):
        project, name = owner.removeprefix("tool:").split("/", 1)
        feedback = RepairFeedback(
            project, name, preview_key=preview_key, context=context, log_run_id=run.id
        )

    def log_event_exception(exception: Exception) -> None:
        preview_logger.opt(exception=exception).error(
            f"预览事件回调执行失败: {type(exception).__name__}: {exception}"
        )
        if feedback:
            feedback.capture(exception, "callback")

    ui.on_exception(log_event_exception)

    phase = "load"
    try:
        with run.context():
            main_func, is_async = load_tool_entrypoint(module_name, str(filepath))
            phase = "render"
            with render_tool_shell(
                title=t("工具预览"),
                subtitle=subtitle,
                mode="preview",
                show_header=not embedded,
            ):
                if is_async:
                    await main_func()
                else:
                    main_func()
    except ToolCapabilityError as error:
        with render_tool_shell(
            title=t("工具预览"),
            subtitle=subtitle,
            mode="preview",
            show_header=not embedded,
        ):
            render_capability_gate(error)
    except Exception as e:
        preview_logger.exception("预览工具执行失败")
        _render_error(
            "工具执行失败",
            "预览代码在运行过程中发生了错误，请查看预览日志获取详情。",
        )
        if feedback:
            feedback.capture(e, phase)
