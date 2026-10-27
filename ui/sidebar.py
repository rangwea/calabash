from nicegui import ui
from component.action_button import action_button
from core.i18n import t
from ui.tool_list import _get_recent_tools, _tool_display_name, use_tool


def _render_desktop_sidebar(
    tools_data: list,
    active_view: str,
    on_select,
    on_chat,
    active_chat=None,
    on_refresh=None,
) -> None:
    recent_tools = _get_recent_tools(tools_data)
    ui.add_css("""
        .calabash-sidebar { background: #f7f8fa; color: #525965; }
        .calabash-sidebar .sidebar-entry {
            min-height: 32px; border-radius: 6px; transition: background .15s, color .15s;
        }
        .calabash-sidebar .sidebar-conversation { height: 32px; min-height: 32px; }
        .calabash-sidebar .sidebar-entry:hover { background: #eceef1; color: #252a33; }
        .calabash-sidebar .sidebar-entry:focus-visible { outline: 2px solid #b9c7da; outline-offset: -2px; }
        .calabash-sidebar .sidebar-selected { background: #e8ebef; color: #252a33; }
        .calabash-sidebar .sidebar-section-label { font-size: 11px; font-weight: 500; color: #969da7; }
        .calabash-sidebar .sidebar-entry .q-icon { flex-shrink: 0; font-size: 16px; color: #8b929d; }
        .calabash-sidebar .sidebar-selected .q-icon { color: #535c69; }
        .conversation-menu.q-menu {
            width: 190px; min-width: 0; max-width: calc(100vw - 16px);
            box-sizing: border-box; overflow-x: hidden;
            padding: 5px; border-radius: 8px;
            background: #fcfcfd; border: 1px solid #dddfe3;
            box-shadow: 0 8px 28px rgb(0 0 0 / 13%), 0 1px 3px rgb(0 0 0 / 5%);
        }
        .conversation-menu .q-item {
            width: 100%; min-width: 0; box-sizing: border-box;
            min-height: 32px; padding: 5px 9px; border-radius: 4px;
            font-size: 13px; color: #30343b;
        }
        .conversation-menu .q-item__section--main {
            min-width: 0; white-space: normal; overflow-wrap: anywhere;
        }
        .conversation-menu .q-item:hover { background: #e9edf2; }
        .conversation-menu .q-item__section--avatar { min-width: 26px; padding-right: 8px; }
        .conversation-menu .q-icon { font-size: 17px; color: #626873; }
        .conversation-menu .q-separator { margin: 4px 6px; background: #e1e3e6; }
        .conversation-menu .menu-danger, .conversation-menu .menu-danger .q-icon { color: #c44545; }
        .conversation-menu .menu-danger:hover { background: #fbeeee; }
    """)
    with ui.column().classes(
        "calabash-sidebar w-56 h-full flex-shrink-0 border-r border-gray-100 gap-0 overflow-y-auto pb-4"
    ):
        with ui.column().classes("w-full px-2 pt-2 gap-0.5"):
            _sidebar_item(
                t("新对话"),
                "edit_square",
                False,
                lambda: on_chat(),
            )
            _sidebar_item(
                t("工具"),
                "folder_open",
                active_view == "tools",
                lambda: on_select("tools"),
            )

        from service.chat.ai_chat import (
            conversations,
            chat_is_pinned,
            pin_chat,
            rename_chat,
            delete_chat,
        )

        def rename_dialog(chat_id, title):
            with ui.dialog() as dialog, ui.card().classes("w-80 max-w-full gap-4"):
                ui.label(t("重命名对话")).classes("text-base font-semibold")
                name = ui.input(label=t("名称"), value=title).classes("w-full")

                def save():
                    if not (name.value or "").strip():
                        ui.notify(t("名称不能为空"), type="warning")
                        return
                    rename_chat(chat_id, name.value)
                    dialog.close()
                    if on_refresh:
                        on_refresh()

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(t("取消"), on_click=dialog.close).props("flat")
                    ui.button(t("保存"), on_click=save)
            dialog.open()

        def remove_dialog(chat_id):
            with ui.dialog() as dialog, ui.card().classes("w-80 max-w-full gap-4"):
                ui.label(t("删除这段对话？")).classes("text-base font-semibold")
                ui.label(t("删除后无法恢复，已创建的工具不受影响。")).classes(
                    "text-sm text-gray-500"
                )

                def remove():
                    delete_chat(chat_id)
                    dialog.close()
                    if active_view == "chat" and chat_id == active_chat:
                        on_chat()
                    if on_refresh:
                        on_refresh()

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(t("取消"), on_click=dialog.close).props("flat")
                    ui.button(t("删除"), on_click=remove).props("color=negative")
            dialog.open()

        def toggle_pin(chat_id, pinned):
            pin_chat(chat_id, not pinned)
            if on_refresh:
                on_refresh()

        with ui.column().classes("w-full px-2 pt-5 gap-0.5"):
            ui.label(t("最近对话")).classes("sidebar-section-label px-2 pb-1.5")
            recent_chats = conversations()[:20]
            for chat_id, title in recent_chats:
                pinned = chat_is_pinned(chat_id)
                selected = active_view == "chat" and chat_id == active_chat
                with ui.element("div").classes(
                    "sidebar-entry sidebar-conversation w-full min-w-0 px-2 py-0 cursor-pointer flex items-center gap-2 "
                    + ("sidebar-selected" if selected else "text-gray-600")
                ).props('data-tool-leave role=button tabindex=0').on(
                    "click", lambda _, cid=chat_id: on_chat(cid),
                    js_handler="(event) => { if (event.target.closest('.calabash-action, .q-menu')) return; emit(); }",
                ).on(
                    "keydown", lambda _, cid=chat_id: on_chat(cid),
                    js_handler="(event) => { if (event.target !== event.currentTarget || !['Enter', ' '].includes(event.key)) return; event.preventDefault(); emit(); }",
                ):
                    if chat_id in getattr(ui.context.client, "calabash_running_chats", set()):
                        ui.spinner(size="14px", color="grey-6").tooltip(t("正在生成回复"))
                    else:
                        ui.icon("push_pin" if pinned else "o_chat_bubble_outline")
                    ui.label(title).classes(
                        "text-xs truncate min-w-0 flex-1"
                    ).tooltip(title)
                    action_button("delete", t("删除对话"), lambda _, cid=chat_id: remove_dialog(cid), compact=True)
                    with (
                        ui.context_menu()
                        .props("auto-close")
                        .classes("conversation-menu")
                    ):
                        with ui.menu_item(
                            on_click=lambda _, cid=chat_id, text=title: rename_dialog(
                                cid, text
                            )
                        ):
                            with ui.item_section().props("avatar"):
                                ui.icon("o_edit")
                            ui.item_section(t("重命名"))
                        with ui.menu_item(
                            on_click=lambda _, cid=chat_id, value=pinned: toggle_pin(
                                cid, value
                            )
                        ):
                            with ui.item_section().props("avatar"):
                                ui.icon("o_push_pin")
                            ui.item_section(t("取消置顶") if pinned else t("置顶"))
                        ui.separator()
                        with ui.menu_item(
                            on_click=lambda _, cid=chat_id: remove_dialog(cid)
                        ).classes("menu-danger"):
                            with ui.item_section().props("avatar"):
                                ui.icon("o_delete")
                            ui.item_section(t("删除对话"))
            if not recent_chats:
                ui.label(t("暂无对话")).classes("px-2 py-1 text-xs text-gray-400")

        with ui.column().classes("w-full px-2 pt-5 gap-0.5"):
            ui.label(t("最近工具")).classes("sidebar-section-label px-2 pb-1.5")
            for tool in recent_tools:
                _sidebar_tool_item(tool)
            if not recent_tools:
                ui.label(t("暂无使用记录")).classes("px-2 py-1 text-xs text-gray-400")

        ui.element("div").classes("flex-1")


def _sidebar_item(label: str, icon: str, active: bool, on_click) -> None:
    classes = (
        "sidebar-entry w-full flex items-center gap-2 px-2 py-1.5 cursor-pointer "
        "transition-colors min-h-[2rem] "
        + (
            "sidebar-selected"
            if active
            else "text-gray-600 hover:bg-[#ececea] hover:text-gray-950"
        )
    )
    with (
        ui.element("div")
        .props("data-tool-leave")
        .classes(classes)
        .on("click", on_click)
    ):
        ui.icon(icon).classes("text-[16px]")
        ui.label(label).classes("text-[13px] font-medium flex-1")


def _sidebar_tool_item(tool: dict) -> None:
    label = _tool_display_name(tool)
    with (
        ui.element("div")
        .classes(
            "sidebar-entry w-full min-w-0 flex items-center gap-2 px-2 py-1.5 cursor-pointer text-gray-600"
        )
        .on("click", lambda t=tool: use_tool(t))
    ):
        ui.icon("terminal").classes("text-[15px] text-gray-400")
        ui.label(label).classes("text-xs truncate min-w-0 flex-1").tooltip(
            f"{label} · {tool.get('project', '')}"
        )
