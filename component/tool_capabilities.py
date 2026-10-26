"""Shared preflight blocker for standalone tools and embedded previews."""

from nicegui import run, ui

from component.capability_settings import CapabilitySettings
from core.i18n import t
from service.capabilities.capability_packs import official_manager
from service.capabilities.tool_capabilities import check_requirements


class ToolCapabilityGate:
    def __init__(self, error, manager=None):
        self.error = error
        self.manager = manager if manager is not None else official_manager()
        self.issues = error.issues

    def render(self):
        with ui.column().classes("w-full max-w-2xl mx-auto py-8 gap-5"):
            ui.icon("o_extension").classes("text-3xl text-gray-400")
            ui.label(t("工具暂未运行")).classes("text-lg font-semibold text-gray-900")
            ui.label(
                t("能力声明格式无效，请让 Agent 修改工具代码。")
                if self.error.invalid else t("请先准备下列能力，再手动重试运行。")
            ).classes("text-sm text-gray-500")
            self.details()
            if not self.error.invalid and any(issue.reason != "unsupported" for issue in self.issues):
                CapabilitySettings(self.manager, on_imported=self.imported).render()
            ui.button(t("重试运行"), icon="replay", on_click=self.retry).props("unelevated no-caps color=dark")

    @ui.refreshable
    def details(self):
        reasons = {
            "missing": "尚未安装所需插件",
            "damaged": "插件损坏或校验未通过，请重新导入",
            "version": "已安装版本不满足要求",
            "unsupported": "当前应用尚不支持此能力，导入 ZIP 无法启用",
        }
        if not self.error.invalid and not self.issues:
            ui.label(t("能力已就绪，请点击重试运行。")).classes("text-sm text-green-700")
        for issue in self.issues:
            with ui.column().classes("w-full gap-1 py-3 border-b border-gray-100"):
                ui.label(issue.requirement.label).classes("text-sm font-medium break-all")
                ui.label(t(reasons[issue.reason])).classes("text-xs text-gray-500")
                if issue.installed:
                    ui.label(t("当前版本：{version}", version=issue.installed)).classes("text-xs text-gray-400")

    async def imported(self, result):
        # Recheck only. Import completion must never execute or reload the tool.
        self.issues = await run.io_bound(check_requirements, self.error.requirements, self.manager)
        await self.details.refresh()

    def retry(self):
        # Preserve preview context and embedded query parameters.
        ui.run_javascript("window.location.reload()")


def render_capability_gate(error):
    ToolCapabilityGate(error).render()
