import json
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from nicegui import ui
from component.action_button import action_button
from core.app_info import APP_NAME, APP_VERSION
from core.i18n import t, language, set_language, LANGUAGES
from core.local_paths import app_dir, database_path, tools_dir
from core.logger import LOG_BASE_DIR, get_logger

logger = get_logger(__name__)


def _render_diagnostics_view(
    tools_data: list,
    project_count: int,
    refresh_tools,
) -> None:
    diagnostics = _collect_diagnostics(
        tools_count=len(tools_data),
        project_count=project_count,
    )
    from component.file_access import access_dialog

    def setting_row(label, value, icon=None, action=None, tooltip=None):
        with ui.row().classes(
            "w-full items-center gap-4 py-3 border-b border-gray-100 last:border-b-0 flex-nowrap"
        ):
            with ui.column().classes("min-w-0 flex-1 gap-1"):
                ui.label(label).classes("text-sm text-gray-800")
                if value:
                    ui.label(value).classes("text-xs text-gray-500 break-all")
            if action:
                action_button({"o_folder_open": "folder", "folder_open": "folder", "content_copy": "copy", "refresh": "refresh"}[icon], tooltip or label, action)

    with ui.column().classes("w-full max-w-3xl mx-auto px-6 sm:px-8 pt-7 pb-10 gap-7"):
        with ui.row().classes("w-full items-center justify-between gap-3"):
            ui.label(t("设置")).classes("text-xl font-semibold text-gray-950")
            ui.label(APP_NAME).classes("text-xs text-gray-400")

        with ui.column().classes("w-full gap-0"):
            ui.label(t("通用")).classes("text-xs font-medium text-gray-400 pb-2")

            def change_language(event):
                if event.value == language():
                    return
                set_language(event.value)
                from nicegui import app

                app.config.language = "en-US" if event.value == "en" else "zh-CN"
                ui.run_javascript(
                    "localStorage.setItem('calabash-language', "
                    + json.dumps(event.value)
                    + "); window.location.reload();"
                )

            ui.select(
                LANGUAGES, value=language(), label=t("语言"), on_change=change_language
            ).props("outlined dense hide-bottom-space").classes("w-full max-w-xs mt-2")

        with ui.column().classes("w-full gap-0"):
            ui.label(t("存储与权限")).classes("text-xs font-medium text-gray-400 pb-2")
            setting_row(
                t("目录访问权限"),
                t("管理已选择的目录与实际访问状态"),
                "o_folder_open",
                access_dialog,
                t("管理目录访问权限"),
            )
            setting_row(
                t("工具目录"),
                diagnostics["工具目录"],
                "folder_open",
                lambda: _open_path(Path(diagnostics["工具目录"])),
                t("打开工具目录"),
            )
            setting_row(
                t("本地数据"),
                diagnostics["本地数据目录"],
                "folder_open",
                lambda: _open_path(Path(diagnostics["本地数据目录"])),
                t("打开数据目录"),
            )
            setting_row(t("SQLite 数据库"), diagnostics["SQLite 路径"])

        with ui.column().classes("w-full gap-0"):
            ui.label(t("工具索引")).classes("text-xs font-medium text-gray-400 pb-2")
            setting_row(
                t("本地工具"),
                t(
                    "{tools} 个工具 · {projects} 个项目",
                    tools=len(tools_data),
                    projects=project_count,
                ),
                "refresh",
                refresh_tools,
                t("刷新工具索引"),
            )

        with ui.column().classes("w-full gap-0"):
            from component.model_settings import render_model_settings

            render_model_settings()

        with ui.column().classes("w-full gap-0"):
            from component.capability_settings import render_capability_settings

            render_capability_settings()

        with ui.column().classes("w-full gap-0"):
            ui.label(t("诊断")).classes("text-xs font-medium text-gray-400 pb-2")
            setting_row(
                t("日志目录"),
                diagnostics["日志目录"],
                "folder_open",
                lambda: _open_path(Path(diagnostics["日志目录"])),
                t("打开日志目录"),
            )
            setting_row(
                t("诊断信息"),
                t("包含版本、运行环境与存储位置"),
                "content_copy",
                lambda: _copy_diagnostics(diagnostics),
                t("复制诊断信息"),
            )
            with (
                ui.expansion(t("最近日志"), icon="o_article")
                .props("dense header-class=px-0")
                .classes("w-full border-0 shadow-none rounded-none mt-2")
            ):
                _render_recent_logs()


def _collect_diagnostics(tools_count: int, project_count: int) -> dict[str, str]:
    app_root = app_dir()
    log_root = LOG_BASE_DIR.resolve()
    return {
        "应用版本": APP_VERSION,
        "运行模式": "Local",
        "Python": platform.python_version(),
        "系统": f"{platform.system()} {platform.release()}",
        "本地数据目录": str(app_root),
        "SQLite 路径": str(database_path()),
        "工具目录": str(tools_dir()),
        "日志目录": str(log_root),
        "工具数量": str(tools_count),
        "项目数量": str(project_count),
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _render_diagnostic_row(label: str, value: str) -> None:
    with ui.row().classes(
        "w-full items-start gap-4 px-4 py-3 border-b border-gray-100 last:border-b-0"
    ):
        ui.label(label).classes("w-28 shrink-0 text-xs font-medium text-gray-500")
        ui.label(value).classes("text-xs text-gray-900 break-all flex-1")


def _render_recent_logs() -> None:
    app_log = LOG_BASE_DIR / "app.log"
    error_log = LOG_BASE_DIR / "error.log"
    with ui.column().classes("w-full gap-3"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(t("最近 8 行日志")).classes("text-xs text-gray-400")

        logs = _read_recent_log_lines(error_log, 8) or _read_recent_log_lines(
            app_log, 8
        )
        if not logs:
            with ui.column().classes("w-full items-center py-10 gap-2"):
                ui.icon("article").classes("text-2xl text-gray-300")
                ui.label(t("暂无日志")).classes("text-sm text-gray-500")
            return

        with ui.element("pre").classes(
            "w-full max-h-60 overflow-auto rounded-md bg-gray-50 text-gray-600 border border-gray-100 "
            "text-xs leading-5 p-4 whitespace-pre-wrap"
        ):
            ui.html(_escape_html("\n".join(logs)), sanitize=False)


def _read_recent_log_lines(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        logger.warning(f"读取日志失败 {path}: {error}")
        return []
    return lines[-limit:]


def _copy_diagnostics(diagnostics: dict[str, str]) -> None:
    text = "\n".join(f"{t(key)}: {value}" for key, value in diagnostics.items())
    ui.clipboard.write(text)
    ui.notify(t("诊断信息已复制"), type="positive")


def _open_path(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", str(path)])
        elif platform.system() == "Windows":
            subprocess.Popen(["explorer", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as error:
        logger.error(f"打开路径失败 {path}: {error}")
        ui.notify(t("打开路径失败: {error}", error=error), type="negative")


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
