"""Calabash 桌面窗口内容 frame。"""

import platform
from collections.abc import Callable

from nicegui import ui

from core.app_info import APP_NAME
from core.i18n import t
from component.action_button import action_button


def render_app_frame(
    *,
    title: str = APP_NAME,
    subtitle: str | None = None,
    action: Callable[[], None] | None = None,
    action_icon: str = "settings",
    action_label: str = "Diagnostics",
) -> None:
    """渲染跨平台内容 frame；窗口控制使用系统原生标题栏。"""
    from component.tool_activity import install_activity_monitor
    install_activity_monitor()
    macos = platform.system() == "Darwin"
    with ui.element("div").props('data-tauri-drag-region="deep"').classes(
        "app-window-frame w-full h-7 flex-shrink-0 flex items-center justify-end "
        "border-b border-gray-100 px-3 sm:px-4 "
        + ("app-window-frame-macos" if macos else "")
    ):
        if action:
            with ui.element("div").props('data-tauri-drag-region="false"'):
                label = t("设置") if action_label == "Diagnostics" else t(action_label)
                button, _ = action_button(action_icon, label, action)
                button.classes("no-drag")


    ui.add_css(
        """
        .app-window-frame {
            background: var(--app-surface); border-color: var(--app-border);
            -webkit-app-region: drag;
            user-select: none;
        }
        /* Native Overlay controls occupy the left inset; the remaining area is draggable. */
        .app-window-frame.app-window-frame-macos {
            height: 36px; min-height: 36px; flex-basis: 36px;
            padding-left: 96px; padding-right: 12px;
            border: 0; background: var(--app-background);
        }
        .app-window-frame .q-btn {
            width: 26px; height: 26px; min-width: 26px; min-height: 26px;
            padding: 4px; border-radius: 6px;
        }
        .app-window-frame .q-btn .q-icon { font-size: 17px; }
        .app-window-frame .q-btn:hover { background: var(--app-hover); }
        .app-window-frame .no-drag,
        .app-window-frame [data-tauri-drag-region=\"false\"] {
            -webkit-app-region: no-drag;
        }
        """,
        shared=True,
    )
