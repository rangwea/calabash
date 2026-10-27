"""Calabash 桌面窗口内容 frame。"""

from collections.abc import Callable

from nicegui import ui

from core.app_info import APP_NAME
from core.i18n import t
from component.action_button import ACTION_CSS


def render_app_frame(
    *,
    title: str = APP_NAME,
    subtitle: str | None = None,
    action: Callable[[], None] | None = None,
    action_icon: str = "o_settings",
    action_label: str = "Diagnostics",
) -> None:
    """渲染跨平台内容 frame；窗口控制使用系统原生标题栏。"""
    from component.tool_activity import install_activity_monitor
    install_activity_monitor()
    with ui.element("div").props('data-tauri-drag-region="deep"').classes(
        "app-window-frame w-full h-7 flex-shrink-0 flex items-center justify-end "
        "bg-white border-b border-gray-100 px-3 sm:px-4"
    ):
        if action:
            with ui.element("div").props('data-tauri-drag-region="false"'):
                ui.add_css(ACTION_CSS, shared=True)
                label = t("设置") if action_label == "Diagnostics" else t(action_label)
                button = ui.button(icon=action_icon, on_click=action, color=None).props(
                    "flat dense"
                ).classes("calabash-action no-drag").tooltip(label)
                button._props["aria-label"] = label

    ui.add_css(
        """
        .app-window-frame {
            -webkit-app-region: drag;
            user-select: none;
        }
        .app-window-frame .q-btn {
            width: 26px; height: 26px; min-width: 26px; min-height: 26px;
            padding: 4px; border-radius: 6px;
        }
        .app-window-frame .q-btn .q-icon { font-size: 17px; }
        .app-window-frame .q-btn:hover { background: #f1f2f3; }
        .app-window-frame .no-drag,
        .app-window-frame [data-tauri-drag-region=\"false\"] {
            -webkit-app-region: no-drag;
        }
        """,
        shared=True,
    )
