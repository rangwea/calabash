"""Explicit disclosure and confirmation before sending a repair request."""

from urllib.parse import urlsplit

from nicegui import ui

from core.i18n import t
from service.chat import model_providers
from service.tools import tool_repairs


class RepairFeedback:
    def __init__(self, project, name, *, show_retry=True, **source):
        self.project, self.name, self.source = project, name, source
        self.report_id = None
        ui.add_css("""
            .tool-repair-action.q-btn {
                min-height: 30px; padding: 4px 8px; border-radius: 6px;
                color: #525966; font-size: 13px; font-weight: 500;
                line-height: 20px; letter-spacing: 0;
            }
            .tool-repair-action.q-btn .q-icon {
                width: 16px; height: 16px; font-size: 16px; margin-right: 6px;
            }
            .tool-repair-action.q-btn:hover { color: #24282e; background: #00000005; }
        """)
        with ui.row().classes("items-center gap-2 w-full px-4 py-2") as self.container:
            self.label = ui.label("").classes("text-sm text-gray-500")
            self.button = ui.button(t("让 Agent 修复"), icon="o_auto_fix_high", on_click=self.confirm).props("flat dense no-caps").classes("tool-repair-action")
            if show_retry:
                ui.button(t("重试运行"), icon="o_restart_alt", on_click=lambda: ui.run_javascript("window.location.reload()")).props("flat dense no-caps").classes("tool-repair-action")
        self.container.set_visibility(False)

    def capture(self, error, phase="render"):
        try:
            self.report_id = tool_repairs.capture(error, self.project, self.name, phase=phase, **self.source)
        except (ValueError, OSError):
            return
        self.label.set_text(t("工具运行失败，详细日志保留在本机。"))
        self.container.set_visibility(True)

    async def confirm(self):
        if not self.report_id:
            return
        try:
            provider, model, connection = model_providers.active()
            fingerprint = tool_repairs.model_fingerprint()
            report = tool_repairs.get(self.report_id)
        except ValueError:
            ui.notify(t("请先配置模型"), type="warning")
            return
        with self.container, ui.dialog() as dialog, ui.card().classes("w-full max-w-lg gap-3"):
            ui.label(t("确认发送修复请求")).classes("text-lg font-semibold")
            ui.label(f"{model} · {urlsplit(connection['base_url']).hostname or provider}").classes("text-sm")
            ui.code(tool_repairs.summary(report)).classes("w-full")
            ui.label(t("将发送以上摘要，并允许模型读取、修改当前工具代码。不发送附件正文或完整日志。修复后不会自动运行，请手动重试。")).classes("text-sm text-gray-500")
            with ui.row():
                ui.button(t("取消"), on_click=lambda: dialog.submit(False)).props("flat")
                ui.button(t("确认发送"), on_click=lambda: dialog.submit(True)).props("unelevated")
        if not await dialog:
            return
        try:
            tool_repairs.approve(self.report_id, fingerprint)
        except ValueError:
            ui.notify(t("请求未发送，请检查原对话和模型配置后重试"), type="warning")
            return
        self.label.set_text(t("修复请求已排队，请在对话中查看。修复后手动重试。"))
        if not self.source.get("preview_key"):
            ui.navigate.to(f"/?repair={self.report_id}")
