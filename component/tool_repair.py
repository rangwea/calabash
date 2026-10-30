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
        except ValueError:
            ui.notify(t("请先配置模型"), type="warning")
            return
        try:
            report = tool_repairs.get(self.report_id)
            from service.tools import tool_diagnostics
            if not tool_diagnostics.is_latest(report) or tool_diagnostics.current_revision(report) != report["revision"]:
                raise ValueError("Stale failure")
        except (ValueError, OSError):
            ui.notify(t('错误记录已过期或代码已更改，请手动重试工具后重新发起修复。'), type='warning')
            return
        with self.container, ui.dialog() as dialog, ui.card().classes("w-full max-w-lg gap-3"):
            ui.label(t("确认发送修复请求")).classes("text-lg font-semibold")
            ui.label(f"{model} · {urlsplit(connection['base_url']).hostname or provider}").classes("text-sm")
            ui.label(t('本次只修改预览版本；手动验证后请保存到工具列表。') if report.get('preview_key') else t('本次修改正式工具；保存后仍需手动运行验证。')).classes('text-sm text-gray-600')
            ui.code(tool_repairs.summary(report)).classes("w-full max-h-64 overflow-auto")
            ui.label(t("确认后会在原对话中追加修复请求，保留已有上下文。Agent 可按需查询当前工具本次失败的日志并修改对应版本；日志可能包含业务信息，已知密钥会过滤。不会自动附加日志全文，修复后请手动重试。")).classes("text-sm text-gray-500")
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
            parent_repair = getattr(ui.context.client, 'calabash_parent_repair', None)
            if parent_repair:
                parent_repair(self.report_id)
            else:
                ui.navigate.to(f"/?repair={self.report_id}")
