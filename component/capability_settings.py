"""Local capability ZIP imports; no network or browser upload fallback."""

from pathlib import Path

from nicegui import run, ui

from component.file_access import choose_path
from component.action_button import app_icon
from core.i18n import t
from core.logger import get_logger
from service.capabilities.capability_manifest import PackError
from service.capabilities.capability_packs import official_manager

logger = get_logger(__name__)


def import_error(error):
    if isinstance(error, PermissionError):
        return t("无法读取插件文件，请检查访问权限")
    code = error.code if isinstance(error, PackError) else "install_failed"
    messages = {
        "not_configured": "此版本尚未配置插件信任公钥，暂不可导入",
        "engine_check_unavailable": "此版本尚不支持该插件引擎",
        "signature_invalid": "插件签名无效，请从可信发布页面重新下载",
        "platform_unavailable": "插件不适用于当前系统或架构",
        "incompatible_manifest": "插件与当前应用版本不兼容",
        "version_rollback": "不能安装比当前已安装版本更旧的插件",
        "disk_full": "磁盘空间不足，请清理后重试",
        "busy": "插件正在使用或安装中，请稍后重试",
        "selfcheck_failed": "插件自检未通过，原有版本保持不变",
        "cancelled": "已取消导入",
    }
    if code in {"archive_hash_mismatch", "file_hash_mismatch", "size_mismatch"}:
        return t("插件文件校验失败，请重新下载")
    if code in {"unsafe_archive", "unsafe_path", "invalid_manifest", "invalid_archive", "missing_file",
                "invalid_entry", "manifest_too_large", "archive_limit", "unknown_package"}:
        return t("不是受支持的插件 ZIP，或包内容不安全")
    return t(messages.get(code, "插件导入失败，请查看诊断日志"))


class CapabilitySettings:
    def __init__(self, manager=None, on_imported=None):
        self.manager = manager if manager is not None else official_manager()
        self.on_imported = on_imported
        self.busy = False

    def render(self):
        with ui.column().classes("w-full gap-3") as self.container:
            ui.label(t("能力插件")).classes("app-section-title")
            with ui.row().classes("w-full items-center gap-3 flex-nowrap"):
                with ui.column().classes("flex-1 min-w-0 gap-1"):
                    ui.label(t("本地 ZIP")).classes("text-sm text-gray-800")
                    ui.label(str(self.manager.root)).classes("text-xs text-gray-500 break-all")
                self.button = ui.button(on_click=self.select).props(
                    "outline no-caps color=primary"
                ).classes("shrink-0")
                self.button._props["aria-label"] = t("导入 ZIP")
                with self.button:
                    app_icon("upload")
                    ui.label(t("导入 ZIP")).classes("ml-1")
            self.progress = ui.linear_progress().props("indeterminate color=primary").classes("w-full")
            self.progress.set_visibility(False)
            self.message = ui.label(
                "" if self.manager.configured else t("此版本尚未配置插件信任公钥，暂不可导入")
            ).classes("text-xs text-gray-500 break-words")
            self.installed = ui.label(t("正在检测媒体插件…")).classes("text-xs text-gray-500")
            ui.timer(0.1, self.load_status, once=True)

    async def load_status(self):
        try:
            result = await run.io_bound(self.manager.status, "media.ffmpeg")
            self.show_status(result)
        except (OSError, ValueError):
            self.installed.set_text(t("媒体插件不可用"))

    def show_status(self, result):
        self.installed.set_text(
            t("FFmpeg {version} · 可用", version=result["version"])
            if result["state"] == "ready" else t("媒体插件未安装或不可用")
        )

    async def select(self):
        if self.busy:
            return
        self.busy = True
        self.button.disable()
        try:
            if not self.manager.configured:
                self.message.set_text(t("此版本尚未配置插件信任公钥，暂不可导入"))
                return
            path = await choose_path(filters=[{"name": "ZIP", "extensions": ["zip"]}])
            if not path:
                return
            if not isinstance(path, str) or Path(path).suffix.lower() != ".zip":
                self.message.set_text(t("请选择 ZIP 插件文件"))
                return
            if not await self.confirm(path):
                return
            self.message.set_text(t("正在校验并导入插件…"))
            self.progress.set_visibility(True)
            result = await run.io_bound(self.manager.import_zip, path)
            self.message.set_text(t("已导入 {name} · {version}", name=result["id"], version=result["version"]))
            self.show_status(result)
            if self.on_imported is not None:
                await self.on_imported(result)
        except (OSError, PackError) as error:
            logger.warning(f"Local plugin import failed: {error}")
            self.message.set_text(import_error(error))
        except Exception:
            logger.exception("Unexpected local plugin import failure")
            self.message.set_text(t("插件导入失败，请查看诊断日志"))
        finally:
            self.busy = False
            self.button.enable()
            self.progress.set_visibility(False)

    async def confirm(self, path):
        with self.container, ui.dialog() as dialog, ui.card().classes("w-96 max-w-full gap-4"):
            ui.label(t("导入插件？")).classes("text-base font-semibold")
            ui.label(Path(path).name).classes("text-sm break-all")
            ui.label(t("插件包含可执行程序，请仅导入可信发布者提供的包。")).classes("text-xs text-gray-500")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(t("取消"), on_click=lambda: dialog.submit(False)).props("flat")
                ui.button(t("导入 ZIP"), on_click=lambda: dialog.submit(True)).props("unelevated color=primary")
        try:
            return await dialog
        finally:
            dialog.delete()


def render_capability_settings():
    CapabilitySettings().render()
