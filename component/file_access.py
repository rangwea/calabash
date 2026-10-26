"""Native desktop selection and local directory access checks."""

import json
import os
import platform
import subprocess

from nicegui import ui

from core.i18n import t
from core.local_paths import app_dir


async def choose_path(*, directory=False, filters=None):
    options = {"directory": directory, "multiple": False, "title": t("选择目录") if directory else t("选择文件")}
    if filters:
        options["filters"] = filters
    result = await ui.run_javascript("""
        const bridge = window.__TAURI_INTERNALS__ || window.parent.__TAURI_INTERNALS__;
        if (!bridge) return {error: 'desktop_required'};
        try { return {path: await bridge.invoke('plugin:dialog|open', {options: OPTIONS})}; }
        catch (error) { return {error: 'picker_failed'}; }
    """.replace("OPTIONS", json.dumps(options)), timeout=300)
    if result and result.get("error"):
        ui.notify(t("请在 Calabash 桌面应用中选择文件") if result["error"] == "desktop_required" else t("无法打开系统选择器，请重启应用后重试"), type="warning")
    return result.get("path") if result else None


async def select_file(target):
    path = await choose_path()
    if path:
        target.set_value(path)


async def choose_paths():
    result = await ui.run_javascript("""
        const bridge = window.__TAURI_INTERNALS__ || window.parent.__TAURI_INTERNALS__;
        if (!bridge) return {error: 'desktop_required'};
        try { return {paths: await bridge.invoke('plugin:dialog|open', {options: {multiple: true, directory: false}})}; }
        catch (error) { return {error: 'picker_failed'}; }
    """, timeout=300)
    if result and result.get("error"):
        ui.notify(t("请在 Calabash 桌面应用中选择文件") if result["error"] == "desktop_required" else t("无法打开系统选择器，请重启应用后重试"), type="warning")
    paths = result.get("paths") if result else None
    return paths if isinstance(paths, list) else []


async def choose_chat_files():
    """Return a native single-use selection ticket, never browser-provided paths."""
    return await ui.run_javascript("""
        const bridge = window.__TAURI_INTERNALS__;
        if (!bridge) return {browser: true};
        try { return {ticket: await bridge.invoke('select_chat_files')}; }
        catch (error) { return {error: 'picker_failed', detail: String(error)}; }
    """, timeout=300)


def _read_directories():
    try:
        data = json.loads((app_dir() / "directory_access.json").read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_directories(paths):
    app_dir().mkdir(parents=True, exist_ok=True)
    (app_dir() / "directory_access.json").write_text(json.dumps(paths, ensure_ascii=False), encoding="utf-8")


def check_directory(path):
    try:
        with os.scandir(path) as entries:
            next(entries, None)
        return t("可访问")
    except PermissionError:
        return t("无访问权限")
    except OSError:
        return t("目录不存在或不可用")


def access_dialog():
    paths = _read_directories()

    async def add():
        path = await choose_path(directory=True)
        if path:
            if path not in paths:
                paths.append(path)
                _save_directories(paths)
            rows.refresh()

    def remove(path):
        paths.remove(path)
        _save_directories(paths)
        rows.refresh()

    @ui.refreshable
    def rows():
        if not paths:
            ui.label(t("尚未选择目录")).classes("text-sm text-gray-400 py-4")
        for path in paths:
            with ui.row().classes("w-full items-center gap-3 flex-nowrap"):
                with ui.column().classes("flex-1 min-w-0 gap-1"):
                    ui.label(path).classes("text-sm break-all")
                    ui.label(check_directory(path)).classes("text-xs text-gray-500")
                ui.button(icon="close", on_click=lambda _, p=path: remove(p)).props("flat dense round").tooltip(t("移除记录（不会撤销系统权限）"))

    with ui.dialog() as dialog, ui.card().classes("w-[560px] max-w-full gap-4"):
        ui.label(t("目录访问权限")).classes("text-base font-semibold")
        ui.label(t("选择目录后检测实际访问状态。移除记录不会撤销 macOS 系统授权。")).classes("text-xs text-gray-500")
        rows()
        with ui.row().classes("w-full items-center gap-2"):
            ui.button(t("选择目录"), icon="folder_open", on_click=add)
            ui.button(icon="refresh", on_click=rows.refresh).props("flat round").tooltip(t("重新检测"))
            if platform.system() == "Darwin":
                ui.button(t("系统权限设置"), on_click=lambda: subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders"])).props("flat")
            ui.button(t("关闭"), on_click=dialog.close).props("flat")
    dialog.open()
