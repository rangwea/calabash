from pathlib import Path

from fastapi import Request
from nicegui import ui
from core.app_info import APP_NAME

from core.i18n import t, language

from component.app_frame import render_app_frame
from component.tool_transfer import ToolTransfer
from core.error_handler import handle_service_errors
from core.logger import get_logger
from service.tools.tool_index_watcher import consume_tool_change
from service.tools.tool_manage_service import list_tools

from ui.sidebar import _render_desktop_sidebar
from ui.settings import _render_diagnostics_view
from ui.tool_list import (
    _tool_display_name,
    _filter_tools,
    _render_empty_state,
    _render_project_section,
)

logger = get_logger(__name__)

_BODY_SCROLL = "flex-1 min-h-0 w-full overflow-y-auto bg-white gap-0"
_INPUT_PROPS = "outlined dense color=primary clearable"


@ui.page("/")
@handle_service_errors("用户页面加载失败")
def home_page(request: Request):
    """用户首页 - 浏览和使用工具"""
    render_desktop_home(repair_id=request.query_params.get("repair"))


def render_desktop_home(repair_id: str | None = None) -> None:
    """渲染桌面版首页。"""
    ui.page_title(APP_NAME)
    ui.context.client.page.language = "en-US" if language() == "en" else "zh-CN"
    ui.add_css("""
        .tool-row-action.q-btn {
            width: 30px; height: 30px; min-width: 30px; min-height: 30px;
            padding: 0; border-radius: 6px; color: #747b84;
        }
        .tool-row-action.q-btn .q-icon { font-size: 18px; }
        .tool-row-action.q-btn:hover { color: #252b33; background: #e9edf1; }
    """)
    active_view = {"name": "tools"}
    chat_state = {"id": None, "switch": None}
    if repair_id:
        from service.tools.tool_repairs import get

        try:
            report = get(repair_id)
            if report["chat_id"] and report["state"] in {
                "queued",
                "running",
                "failed",
                "completed",
            }:
                active_view["name"] = "chat"
                chat_state["id"] = report["chat_id"]
        except ValueError:
            pass

    def load_tools() -> list:
        logger.debug("加载工具和项目数据")
        try:
            return list_tools()
        except Exception as e:
            logger.error(f"获取工具列表失败: {e}")
            ui.notify(t("获取工具列表失败"), type="negative")
            return []

    tools_data = load_tools()
    project_names = sorted({t.get("project", "未分组") for t in tools_data})
    logger.info(f"加载到 {len(tools_data)} 个工具，{len(project_names)} 个项目")

    def navigate_view(view_name: str) -> None:
        active_view["name"] = view_name
        sidebar.refresh()
        workspace.refresh()

    def chat_changed(chat_id):
        chat_state["id"] = chat_id
        sidebar.refresh()

    def open_chat(chat_id=None):
        if active_view["name"] == "chat" and chat_state["switch"]:
            chat_state["switch"](chat_id)
        else:
            chat_state["id"] = chat_id
            navigate_view("chat")

    def discuss_tool(tool):
        from service.chat.ai_chat import create_tool_chat

        open_chat(
            create_tool_chat(tool["project"], tool["name"], _tool_display_name(tool))
        )

    sidebar_state = {"expanded": True}

    def toggle_sidebar() -> None:
        sidebar_state["expanded"] = not sidebar_state["expanded"]
        sidebar_container.set_visibility(sidebar_state["expanded"])
        sidebar_divider.set_visibility(sidebar_state["expanded"])
        if sidebar_button:
            sidebar_button.props(f'aria-expanded={str(sidebar_state["expanded"]).lower()}')

    with ui.column().classes("w-full h-screen overflow-hidden bg-white gap-0"):
        render_app_frame(
            action=lambda: navigate_view("diagnostics"),
        )

        with ui.row().classes(
            "w-full flex-1 min-h-0 overflow-hidden gap-0 flex-nowrap"
        ):

            @ui.refreshable
            def sidebar() -> None:
                _render_desktop_sidebar(
                    tools_data,
                    active_view["name"],
                    navigate_view,
                    open_chat,
                    chat_state["id"],
                    sidebar.refresh,
                )

            from component.panel_resize import resize_handle

            with ui.element("div").classes("relative h-full flex-shrink-0"):
                with ui.element("nav").props('id=desktop-sidebar data-testid=desktop-sidebar').classes(
                    "w-56 h-full min-h-0 overflow-hidden pt-9 bg-gray-50"
                ) as sidebar_container:
                    with ui.row().classes(
                        "absolute top-0 left-0 right-9 h-9 items-center gap-2 px-3 flex-nowrap overflow-hidden"
                    ).props("data-testid=sidebar-brand"):
                        ui.image(str(Path(__file__).resolve().parents[2] / "component/assets/calabash.png")).props(
                            f'no-spinner fit=contain alt="{APP_NAME}"'
                        ).classes("w-5 h-5 shrink-0")
                        ui.label(APP_NAME).classes("text-sm font-medium text-gray-700 truncate")
                    sidebar()
                sidebar_button = ui.button(icon="o_view_sidebar", on_click=toggle_sidebar).props(
                    'flat dense round size=sm color=grey-7 data-testid=sidebar-toggle '
                    f'aria-expanded=true aria-controls=desktop-sidebar aria-label="{t("切换侧边栏")}"'
                ).classes("absolute top-1 right-1 z-10").tooltip(t("切换侧边栏"))
                # Keep a narrow, reachable expansion control when the menu is hidden.
                ui.element("div").classes("w-8 h-9").bind_visibility_from(
                    sidebar_state, "expanded", backward=lambda value: not value
                )
            sidebar_divider = resize_handle(label="调整菜单宽度", minimum=180, maximum=360)
            sidebar_divider.props("data-panel=desktop-sidebar")

            with ui.column().classes("flex-1 min-w-0 h-full overflow-hidden gap-0"):
                with ui.column().classes(_BODY_SCROLL):

                    @ui.refreshable
                    def workspace():
                        if active_view["name"] == "chat":
                            from component.ai_chat import render_ai_chat

                            with ui.column().classes("w-full h-full min-h-0 gap-0"):
                                chat_state["switch"] = render_ai_chat(
                                    chat_state["id"],
                                    on_change=chat_changed,
                                )
                            return
                        if active_view["name"] == "diagnostics":
                            _render_diagnostics_view(
                                tools_data=tools_data,
                                project_count=len(project_names),
                                refresh_tools=lambda: refresh_tool_data(force=True),
                            )
                            return

                        with ui.column().classes(
                            "w-full max-w-4xl mx-auto px-8 pt-2 pb-10 gap-6"
                        ):
                            with ui.row().classes("w-full items-center justify-between gap-3"):
                                ui.label(t("工具")).classes(
                                    "text-[26px] font-semibold text-gray-950"
                                )
                                transfer = ToolTransfer(lambda: refresh_tool_data(notify=False, force=True))
                                transfer.render()

                            search = (
                                ui.input(placeholder=t("搜索工具"))
                                .props(_INPUT_PROPS + " prefix=search")
                                .classes("w-full")
                            )

                            @ui.refreshable
                            def render_tools():
                                filtered = _filter_tools(
                                    tools_data,
                                    (search.value or "").strip().lower(),
                                )
                                if not filtered:
                                    _render_empty_state()
                                    return

                                grouped: dict[str, list] = {}
                                for tool in filtered:
                                    key = tool.get("project", "未分组")
                                    grouped.setdefault(key, []).append(tool)

                                with ui.column().classes("w-full gap-8 pt-2"):
                                    for project_name, project_tools in sorted(
                                        grouped.items()
                                    ):
                                        _render_project_section(
                                            project_name, project_tools, discuss_tool,
                                            lambda: refresh_tool_data(notify=False, force=True),
                                        )

                            search.on("change", lambda _: render_tools.refresh())
                            render_tools()

                    workspace()

        def refresh_tool_data(*, notify: bool = True, force: bool = False) -> None:
            nonlocal tools_data, project_names
            if not force and not consume_tool_change():
                return
            tools_data = load_tools()
            project_names = sorted({t.get("project", "未分组") for t in tools_data})
            sidebar.refresh()
            if active_view["name"] != "chat":
                workspace.refresh()
            if notify:
                ui.notify(t("工具索引已刷新"), type="positive")

        # Agent 直接写入工具目录后，首页在几秒内静默同步索引。
        ui.timer(1.0, lambda: refresh_tool_data(notify=False))
