import json
from nicegui import ui
from core.i18n import t
from core.local_paths import app_dir
from core.logger import get_logger
from service.tools.tool_manage_service import delete_tool
from service.tools.tool_activity import ToolBusyError
from component.tool_transfer import export_tool
from component.action_button import action_button, app_icon, menu_item

logger = get_logger(__name__)
_RECENT_TOOLS_FILE = app_dir() / "recent_tools.json"
_PROJECT_TONES = [
    "bg-blue-50 text-blue-700",
    "bg-violet-50 text-violet-700",
    "bg-emerald-50 text-emerald-700",
    "bg-amber-50 text-amber-700",
    "bg-rose-50 text-rose-700",
    "bg-cyan-50 text-cyan-700",
]


def _filter_tools(
    tools_data: list,
    query: str,
) -> list:
    def match_tool(t: dict) -> bool:
        if query:
            name = _tool_display_name(t).lower()
            identifier = (t.get("name") or "").lower()
            desc = (t.get("description") or "").lower()
            if query not in name and query not in identifier and query not in desc:
                return False
        return True

    return [t for t in tools_data if match_tool(t)]


def _get_recent_tools(tools_data: list[dict]) -> list[dict]:
    """按本地使用记录返回最近工具；没有记录时保持空状态。"""
    try:
        recent_keys = json.loads(_RECENT_TOOLS_FILE.read_text(encoding="utf-8"))
        if not isinstance(recent_keys, list):
            return []
    except (OSError, json.JSONDecodeError):
        return []

    tools_by_key = {_tool_key(tool): tool for tool in tools_data}
    return [tools_by_key[key] for key in recent_keys if key in tools_by_key][:6]


def _tool_key(tool: dict) -> str:
    return f"{tool.get('project', '')}/{tool.get('name', '')}"


def _record_recent_tool(tool: dict) -> None:
    key = _tool_key(tool)
    if key == "/":
        return
    try:
        recent_keys = json.loads(_RECENT_TOOLS_FILE.read_text(encoding="utf-8"))
        if not isinstance(recent_keys, list):
            recent_keys = []
    except (OSError, json.JSONDecodeError):
        recent_keys = []
    recent_keys = [key, *[item for item in recent_keys if item != key]][:12]
    try:
        _RECENT_TOOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RECENT_TOOLS_FILE.write_text(
            json.dumps(recent_keys, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as error:
        logger.warning(f"保存最近工具失败: {error}")


def _render_empty_state() -> None:
    with ui.column().classes("w-full items-center py-14 gap-2"):
        ui.icon("inbox").classes("text-3xl text-gray-300")
        ui.label(t("未找到匹配的工具")).classes("text-sm text-gray-500")
        ui.label(t("换个关键词试试")).classes("text-xs text-gray-400")


def _render_project_section(
    project_name: str,
    project_tools: list,
    on_chat=None,
    on_delete=None,
    on_open=None,
) -> None:
    with ui.column().classes("app-tool-group w-full gap-3"):
        with ui.row().classes(
            "w-full items-center justify-between border-b border-gray-100 pb-2"
        ):
            ui.label(project_name).classes("text-sm font-medium text-gray-900")
            ui.label(f"{len(project_tools)}").classes("text-xs text-gray-400")

        with ui.column().classes("w-full gap-0"):
            for tool in project_tools:
                _render_tool_row(tool, on_chat, on_delete, on_open)


def _render_tool_tag(label: str, project_name: str) -> None:
    ui.label(label).classes(
        "app-tool-tag text-[11px] "
        "px-1.5 py-0.5 rounded max-w-32 truncate"
    )


def _render_tool_row(tool: dict, on_chat=None, on_delete=None, on_open=None) -> None:
    open_tool = on_open or use_tool
    display_name = _tool_display_name(tool)
    description = tool.get("description") or t("暂无描述")
    tool_tags = _parse_tags(tool)
    project_name = tool.get("project") or "未分组"

    with ui.element("div").classes(
        "app-tool-row relative w-full cursor-pointer border-b border-gray-100 py-3 "
        "hover:bg-gray-50 transition-colors"
    ):
        opener = ui.button(on_click=lambda: open_tool(tool), color=None).props("flat dense").classes("row-open-target absolute inset-0 w-full h-full")
        opener._props["aria-label"] = t("打开工具") + " " + display_name
        with ui.row().classes("w-full items-center gap-3 px-1 pointer-events-none"):
            with ui.element("div").classes(
                "app-tool-icon w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
            ):
                app_icon("grid")
            with (
                ui.column()
                .classes("min-w-0 flex-1 gap-0")
            ):
                ui.label(display_name).classes(
                    "text-sm font-medium text-gray-950 truncate"
                )
                ui.label(description).classes("text-xs text-gray-500 truncate")
            if tool_tags:
                with ui.row().classes("gap-1 flex-wrap shrink-0"):
                    for tag in tool_tags[:2]:
                        _render_tool_tag(tag, project_name)
            with ui.row().classes("gap-1 items-center shrink-0 pointer-events-auto relative"):
                if on_chat:
                    action_button("chat", t("对话修改工具"), lambda _, item=tool: on_chat(item))
                action_button("open", t("打开工具"), lambda _, item=tool: open_tool(item))
                more, _ = action_button("more", t("更多操作"), None)
                with more, ui.menu().props("auto-close").classes("app-action-menu"):
                    menu_item("download", t("导出工具 ZIP"), lambda: export_tool(tool))
                    if on_delete:
                        ui.separator()
                        menu_item("delete", t("删除工具"), lambda: _confirm_delete_tool(tool, on_delete), danger=True)



def _confirm_delete_tool(tool, on_deleted):
    with ui.dialog() as dialog, ui.card().classes("w-96 max-w-full gap-4"):
        ui.label(t("删除工具")).classes("text-base font-semibold")
        ui.label(
            t("确定永久删除工具“{name}”吗？", name=_tool_display_name(tool))
        ).classes("text-sm break-words w-full")
        ui.label(t("历史对话、结果文件和日志将保留。此操作无法撤销。")).classes(
            "text-xs text-gray-500"
        )

        def confirm():
            try:
                delete_tool(tool["project"], tool["name"], revision=tool["revision"])
            except ToolBusyError:
                ui.notify(t("工具正在执行，请等待任务结束后再删除"), type="warning")
                return
            except ValueError:
                ui.notify(t("工具已变更或不可删除，请刷新列表后重试"), type="warning")
                return
            except Exception:
                logger.exception("Tool deletion failed")
                ui.notify(t("删除工具失败，请重试"), type="negative")
                return
            dialog.close()
            on_deleted()
            ui.notify(t("工具已删除"), type="positive")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("取消"), on_click=dialog.close).props("flat color=grey-7")
            ui.button(t("删除"), on_click=confirm).props("unelevated color=negative")
    dialog.open()


def _project_tone(project_name: str) -> str:
    index = sum(ord(char) for char in project_name) % len(_PROJECT_TONES)
    return _PROJECT_TONES[index]


def _parse_tags(tool: dict) -> list[str]:
    return [tag.strip() for tag in (tool.get("tags") or "").split(",") if tag.strip()]


def _tool_meta_line(tool: dict) -> str:
    parts: list[str] = []
    if tool.get("creator"):
        parts.append(tool["creator"])
    if tool.get("created_at"):
        parts.append(str(tool["created_at"]))
    return " · ".join(parts)


def _tool_display_name(tool: dict) -> str:
    return tool.get("title") or tool.get("name") or t("未命名工具")


def use_tool(tool: dict) -> None:
    try:
        logger.info(f"用户使用工具: {tool.get('name')}")
        _record_recent_tool(tool)
        project_name = tool.get("project", "")
        tool_name = tool.get("name", "")
        if not project_name or not tool_name:
            raise ValueError("工具项目或文件标识为空")
        ui.navigate.to(f"/tools/{project_name}/{tool_name}")
    except Exception as e:
        logger.error(f"打开工具失败: {e}")
        ui.notify(t("打开工具失败: {error}", error=e), type="negative")
