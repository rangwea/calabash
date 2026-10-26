"""Local tool ZIP import confirmation and native export delivery."""

import json

from nicegui import run, ui

from component.file_access import choose_path
from core.i18n import t
from core.logger import get_logger
from service.tools import tool_archives as archives

logger = get_logger(__name__)


def transfer_error(error):
    messages = {
        "identity": "项目和工具标识只能使用小写字母、数字、下划线和连字符",
        "format": "不是受支持的工具 ZIP，或包内容不安全",
        "source": "工具源码无效，必须包含顶层 main() 函数",
        "limit": "工具包过大：ZIP 最大 2 MB，源码最大 1 MB",
        "path": "目标工具位置不安全，无法导入或导出",
        "busy": "工具正在执行，请等待任务结束后再覆盖",
        "conflict": "已存在同名工具，请重命名或确认覆盖",
        "changed": "目标工具已变更，请重新确认后导入",
    }
    if isinstance(error, PermissionError):
        return t("无法访问文件，请检查目录权限")
    return t(messages.get(getattr(error, "code", None), "工具导入导出失败，请重试"))


class ToolTransfer:
    def __init__(self, on_changed):
        self.on_changed = on_changed
        self.busy = False

    def render(self):
        with ui.column().classes("gap-0 shrink-0") as self.container:
            self.button = (
                ui.button(t("导入工具"), icon="o_file_upload", on_click=self.select)
                .props("flat dense no-caps color=grey-7")
                .tooltip(t("从本地 ZIP 导入工具"))
            )

    async def select(self):
        if self.busy:
            return
        self.busy = True
        self.button.disable()
        imported = False
        try:
            path = await choose_path(
                filters=[{"name": "Calabash ZIP", "extensions": ["zip"]}]
            )
            if not path:
                return
            package = await run.io_bound(archives.inspect_zip, path)
            imported = await self.confirm(package)
        except (OSError, ValueError, RuntimeError) as error:
            logger.warning(f"Tool ZIP import failed: {type(error).__name__}")
            ui.notify(transfer_error(error), type="negative")
        finally:
            self.busy = False
            self.button.enable()
        if imported:
            self.on_changed()
            ui.notify(t("工具已导入"), type="positive")

    async def confirm(self, package):
        with (
            self.container.client.layout,
            ui.dialog() as dialog,
            ui.card().classes("w-[440px] max-w-full gap-4"),
        ):
            ui.label(t("导入工具")).classes("text-base font-semibold")
            ui.label(package.title).classes("text-sm font-medium break-words w-full")
            ui.label(package.description or t("暂无描述")).classes(
                "text-xs text-gray-500 break-words w-full"
            )
            if package.requires:
                ui.label(t("依赖能力：{requires}", requires=package.requires)).classes(
                    "text-xs text-gray-500 break-all w-full"
                )
            project = (
                ui.input(t("项目标识"), value=package.project)
                .props("outlined dense hide-bottom-space")
                .classes("w-full")
            )
            name = (
                ui.input(t("工具标识"), value=package.name)
                .props("outlined dense hide-bottom-space")
                .classes("w-full")
            )
            message = ui.label().classes("text-xs text-orange-700 break-words w-full")
            overwrite = ui.checkbox(t("覆盖同名工具（不可撤销）"), value=False).classes(
                "text-sm"
            )
            ui.label(
                t(
                    "工具可执行本地代码，请仅导入可信来源。静态校验不等于安全沙箱；导入不会运行代码或安装依赖。"
                )
            ).classes("text-xs text-gray-500 break-words w-full")
            state = {"revision": None, "valid": False}

            def update_target():
                overwrite.set_value(False)
                try:
                    state["revision"] = archives.target_revision(
                        project.value or "", name.value or ""
                    )
                    state["valid"] = True
                    message.set_text(
                        t("已存在同名工具，请重命名或确认覆盖")
                        if state["revision"] is not None
                        else ""
                    )
                    overwrite.set_visibility(state["revision"] is not None)
                except (OSError, ValueError) as error:
                    state["valid"] = False
                    overwrite.set_visibility(False)
                    message.set_text(transfer_error(error))
                update_enabled()

            def update_enabled():
                accept.set_enabled(
                    state["valid"] and (state["revision"] is None or overwrite.value)
                )

            def install():
                if not state["valid"] or (
                    state["revision"] is not None and not overwrite.value
                ):
                    return
                accept.disable()
                try:
                    archives.install(
                        package,
                        project.value,
                        name.value,
                        expected_revision=state["revision"],
                    )
                except (OSError, ValueError) as error:
                    logger.warning(
                        f"Tool ZIP installation failed: {type(error).__name__}"
                    )
                    update_target()
                    message.set_text(transfer_error(error))
                    return
                dialog.submit(True)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(t("取消"), on_click=lambda: dialog.submit(False)).props(
                    "flat color=grey-7"
                )
                accept = ui.button(t("确认导入"), on_click=install).props(
                    "unelevated color=dark"
                )
            project.on_value_change(lambda _: update_target())
            name.on_value_change(lambda _: update_target())
            overwrite.on_value_change(lambda _: update_enabled())
            update_target()
        try:
            return bool(await dialog)
        finally:
            dialog.delete()


async def export_tool(tool):
    try:
        with archives.export_delivery(tool["project"], tool["name"]) as (data, ticket):
            if not ticket:
                ui.download(
                    data, filename=f"{tool['name']}.zip", media_type="application/zip"
                )
                return
            result = await ui.run_javascript(
                """
                const bridge = window.__TAURI_INTERNALS__ || window.parent.__TAURI_INTERNALS__;
                if (!bridge) return {browser: true};
                try { await bridge.invoke('save_tool_output', {ticket: TICKET}); return {}; }
                catch (_) { return {error: true}; }
            """.replace("TICKET", json.dumps(ticket)),
                timeout=300,
            )
            if result and result.get("browser"):
                ui.download(
                    data, filename=f"{tool['name']}.zip", media_type="application/zip"
                )
            elif result and result.get("error"):
                ui.notify(t("无法保存 ZIP，请选择新的文件名后重试"), type="warning")
    except (OSError, ValueError, RuntimeError) as error:
        logger.warning(f"Tool ZIP export failed: {type(error).__name__}")
        ui.notify(transfer_error(error), type="negative")
