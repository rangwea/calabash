"""
工具相关API接口和页面路由
"""

import subprocess

from fastapi import Request
from nicegui import ui

from component.tool_capabilities import render_capability_gate
from component.tool_repair import RepairFeedback
from component.tool_shell import render_tool_shell
from core.i18n import t
from core.local_paths import logs_dir
from core.logger import get_logger, setup_tool_logging, tool_log_context
from service.capabilities.tool_capabilities import ToolCapabilityError
from service.tools.tool_service import get_tool_by_name, load_and_execute_project_tool

logger = get_logger(__name__)


@ui.page("/tools/{project_name}/{tool_name}")
async def tools_handler(request: Request, project_name: str, tool_name: str):
    """项目工具路由处理器"""
    logger.info(f"Loading project tool: {project_name}/{tool_name}")
    feedback = RepairFeedback(project_name, tool_name)
    ui.on_exception(lambda error: feedback.capture(error, "callback"))
    phase = "load"

    try:
        # 动态加载项目工具
        result = load_and_execute_project_tool(project_name, tool_name)

        if result and len(result) == 2:
            phase = "render"
            tool_func, is_async = result

            # 为用户代码的标准 logging 设置文件 handler（回调场景也生效）
            module_name = f"tools_{project_name}_{tool_name}"
            setup_tool_logging(project_name, tool_name, module_name)
            # 也为 tools.{project_name}.{tool_name} 设置（exec 路径使用的模块名）
            setup_tool_logging(
                project_name, tool_name, f"tools.{project_name}.{tool_name}"
            )

            tool_meta = get_tool_by_name(tool_name, project_name) or {}
            shell_title = tool_meta.get("title") or tool_name
            ui.context.client.calabash_output_owner = (
                f"tool:{project_name}/{tool_name}",
                None,
            )

            with (
                render_tool_shell(
                    title=shell_title,
                    subtitle=project_name,
                    mode="tool",
                ),
                tool_log_context(project_name, tool_name),
            ):
                if is_async:
                    await tool_func()
                else:
                    tool_func()
        else:
            logger.warning(
                f"Invalid result from load_and_execute_project_tool: {result}"
            )

    except ToolCapabilityError as error:
        with render_tool_shell(title=tool_name, subtitle=project_name, mode="tool"):
            render_capability_gate(error)
    except Exception as e:
        error_msg = str(e)
        with tool_log_context(project_name, tool_name):
            logger.exception(f"工具渲染失败: {project_name}/{tool_name}")

        _render_tool_error(error_msg, project_name, tool_name)
        feedback.capture(e, phase)


def _render_tool_error(error_msg: str, project_name: str, tool_name: str) -> None:
    """把运行异常转换为用户可理解的错误状态。"""
    if "工具不存在" in error_msg:
        icon, title, message, tone = (
            "search_off",
            "找不到这个工具",
            "工具文件可能已被移动或删除。",
            "text-gray-600",
        )
    elif "工具加载失败" in error_msg or "没有找到可执行的代码" in error_msg:
        icon, title, message, tone = (
            "build_circle",
            "工具无法加载",
            "工具代码需要定义可执行的 main() 函数。",
            "text-orange-600",
        )
    else:
        icon, title, message, tone = (
            "error_outline",
            "工具运行失败",
            "工具执行时发生错误，详细信息已写入本地日志。",
            "text-red-600",
        )

    with ui.column().classes("items-center justify-center min-h-screen gap-3 px-6"):
        ui.icon(icon, size="3rem").classes(tone)
        ui.label(t(title)).classes(f"text-xl font-semibold {tone}")
        ui.label(t(message)).classes("text-sm text-gray-500 text-center max-w-md")
        ui.label(f"{project_name}/{tool_name}").classes("text-xs text-gray-400")
        ui.button(
            t("返回工具中心"),
            icon="arrow_back",
            on_click=lambda: ui.navigate.to("/"),
        ).props("unelevated color=dark").classes("mt-3")
        ui.button(
            t("查看日志"),
            icon="article",
            on_click=_open_logs,
        ).props("flat dense color=grey-7")


def _open_logs() -> None:
    """打开本地日志目录，不把堆栈直接展示给用户。"""
    try:
        subprocess.Popen(["open", str(logs_dir())])
    except OSError:
        ui.notify(t("日志目录：{path}", path=logs_dir()), type="info")
