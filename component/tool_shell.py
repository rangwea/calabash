"""工具页统一外壳：顶栏导航 + 内容区边距（正式路由与预览共用）。"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Literal

from nicegui import ui

from core.i18n import t, language

from component.app_frame import render_app_frame

TOOL_SHELL_OUTER = "w-full min-h-screen flex flex-col gap-0 bg-[#fafafa]"
# 顶栏/侧栏：仅浅分割线，不用 shadow（与全站轻量表面一致）
BORDER_SUBTLE = "border-gray-100"
TOOL_SHELL_HEADER_BAR = f"w-full flex-shrink-0 gap-0 bg-white border-b {BORDER_SUBTLE}"
PLATFORM_SIDEBAR = f"bg-white border-r {BORDER_SUBTLE}"
SURFACE_CARD = f"border {BORDER_SUBTLE} shadow-none"
TOOL_SHELL_HEADER_INNER = (
    "w-full max-w-screen-2xl mx-auto px-4 sm:px-5 py-1.5 "
    "items-center justify-between gap-3 min-h-[2.75rem]"
)
TOOL_SHELL_BODY_SCROLL = "flex-1 w-full overflow-y-auto gap-0"
TOOL_SHELL_CONTENT = "w-full max-w-screen-2xl mx-auto px-4 sm:px-6 py-4"

ToolShellMode = Literal["tool", "preview"]


def _render_tool_header(
    *,
    title: str | None,
    subtitle: str | None,
    mode: ToolShellMode,
    show_back: bool,
    back_url: str,
) -> None:
    with ui.row().classes(TOOL_SHELL_HEADER_BAR):
        with ui.row().classes(TOOL_SHELL_HEADER_INNER):
            with ui.row().classes("items-center gap-2.5 min-w-0 flex-1"):
                if show_back:
                    ui.button(
                        on_click=lambda: ui.navigate.to(back_url),
                        icon="arrow_back",
                    ).props("flat dense round color=grey-8").classes("shrink-0")
                with ui.column().classes("min-w-0 gap-0"):
                    if title:
                        ui.label(title).classes(
                            "text-[13px] font-semibold text-gray-950 truncate"
                        )
                    if subtitle:
                        ui.label(subtitle).classes("text-[11px] text-gray-500 truncate")
            if mode == "preview":
                ui.label(t("预览")).classes(
                    "text-xs font-medium px-2 py-0.5 rounded-md "
                    "bg-amber-50 text-amber-700 border border-amber-100 shrink-0"
                )


@contextmanager
def render_tool_shell(
    *,
    title: str | None = None,
    subtitle: str | None = None,
    mode: ToolShellMode = "tool",
    show_back: bool = True,
    back_url: str = "/",
    show_header: bool = True,
) -> Generator[None, None, None]:
    """包裹工具/预览 UI：顶栏 + 可滚动内容区（max-w-screen-2xl + 边距）。"""
    ui.context.client.page.language = "en-US" if language() == "en" else "zh-CN"
    with ui.column().classes(TOOL_SHELL_OUTER):
        if show_header:
            render_app_frame()
            _render_tool_header(
                title=title,
                subtitle=subtitle,
                mode=mode,
                show_back=show_back,
                back_url=back_url,
            )
        with ui.column().classes(TOOL_SHELL_BODY_SCROLL):
            with ui.column().classes(TOOL_SHELL_CONTENT):
                yield
