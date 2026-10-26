"""Compact result delivery and batch status controls for generated tools."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from nicegui import run, ui

from core.i18n import t
from service.tools.tool_activity import ToolBusyError
from service.files.tool_outputs import ToolOutputs


class ToolResults:
    def __init__(self, outputs=None):
        self.outputs = outputs or ToolOutputs(owner=getattr(ui.context.client, "calabash_output_owner", None))
        self.limit = 20
        self.container = ui.column().classes("w-full gap-1")
        self.refresh()

    def show_more(self):
        self.limit += 20
        self.refresh()

    def start_run(self):
        self.outputs.start_run()
        self.refresh()

    def refresh(self):
        if self.container.is_deleted:
            return
        items = self.outputs.files(limit=self.limit + 1)
        self.container.clear()
        with self.container:
            with ui.row().classes("w-full items-center justify-end"):
                ui.button(icon="refresh", on_click=self.refresh).props("flat round dense").tooltip(t("刷新结果"))
            if not items:
                ui.label(t("暂无结果文件")).classes("text-sm text-gray-500 py-2")
            run_id = None
            for item in items[:self.limit]:
                if item["run_id"] != run_id:
                    run_id = item["run_id"]
                    timestamp = datetime.fromtimestamp(item["created"], UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
                    label = t("本次运行") if run_id == self.outputs.id else t("历史运行")
                    ui.label(f"{label} · {timestamp}").classes("text-xs text-gray-500 pt-2")
                with ui.row().classes("w-full items-center gap-2 flex-nowrap border-b border-gray-100 py-2"):
                    ui.icon("description").classes("text-gray-400")
                    ui.label(item["name"]).classes("min-w-0 flex-1 break-all text-sm")
                    ui.label(f'{item["size"] / 1024:.1f} KB').classes("text-xs text-gray-400 shrink-0")
                    if not item["available"]:
                        ui.label(t("文件不可用")).classes("text-xs text-gray-500 shrink-0").tooltip(t("文件已被移动、删除或修改"))
                    for icon, label, callback in [
                        ("open_in_new", t("打开"), lambda _, key=item["id"]: self.open(key)),
                        ("folder_open", t("在文件夹中显示"), lambda _, key=item["id"]: self.open(key, reveal=True)),
                        ("download", t("另存为"), lambda _, key=item["id"]: self.download(key)),
                    ]:
                        button = ui.button(icon=icon, on_click=callback).props("flat round dense").tooltip(label)
                        button._props["aria-label"] = f"{label} {item['name']}"
                        if not item["available"]:
                            button.disable()
            if len(items) > self.limit:
                ui.button(t("显示更多"), icon="expand_more", on_click=self.show_more).props("flat dense no-caps")

    async def open(self, key, *, reveal=False):
        try:
            await run.io_bound(lambda: self.outputs.open(key, reveal=reveal))
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
            self.refresh()
            ui.notify(t("无法打开结果文件"), type="warning")

    async def download(self, key):
        try:
            ticket = self.outputs.save_ticket(key)
            if not ticket:
                ui.download(self.outputs.path(key))
                return
            result = await ui.run_javascript("""
                const bridge = window.__TAURI_INTERNALS__ || window.parent.__TAURI_INTERNALS__;
                if (!bridge) return {browser: true};
                try { await bridge.invoke('save_tool_output', {ticket: TICKET}); return {}; }
                catch (_) { return {error: true}; }
            """.replace("TICKET", json.dumps(ticket)), timeout=300)
            if result and result.get("browser"):
                ui.download(self.outputs.path(key))
            elif result and result.get("error"):
                ui.notify(t("无法保存副本，请选择新的文件名"), type="warning")
        except (OSError, ValueError, KeyError):
            self.refresh()
            ui.notify(t("结果文件已变更或不可用"), type="warning")


class ToolJobStatus:
    def __init__(self, jobs, *, inputs=(), controls=()):
        from component.tool_activity import install_activity_monitor
        install_activity_monitor()
        ui.add_css("""
            .tool-job-action.q-btn {
                width: 28px; height: 28px; min-width: 28px; min-height: 28px;
                padding: 0; border-radius: 6px;
            }
            .tool-job-action.q-btn .q-icon { font-size: 16px; }
        """)
        self.jobs = jobs
        self.inputs, self.controls = tuple(inputs), tuple(controls)
        self._starting = False
        self.client = ui.context.client
        owner = getattr(self.client, "calabash_output_owner", None)
        self.jobs.tool_owner = owner[0] if owner else None
        if self.jobs.owner is None:
            self.jobs.owner = owner[0] if owner else self.client.id
        self.handler = None
        self.container = ui.column().classes("w-full gap-1")
        self.refresh()

    async def run(self, handler=None, *, retry_failed=False):
        if self._starting or self.jobs.running:
            return False
        if handler is not None:
            self.handler = handler
        if self.handler is None:
            raise ValueError("A handler is required")
        self._starting = True
        locked = []
        enabled = []
        try:
            for inputs in self.inputs:
                if not inputs.frozen:
                    inputs.freeze()
                    locked.append(inputs)
            for control in self.controls:
                enabled.append((control, control.enabled))
                control.disable()
            if self.client.has_socket_connection:
                await self.client.run_javascript("(window.top.calabashToolRuns || window.calabashToolRuns)?.setBusy(true)", timeout=5)
            with self.container:
                await self.jobs.run(self.handler, retry_failed=retry_failed, changed=self.refresh)
            return True
        except ToolBusyError as error:
            ui.notify(t("应用正在安全退出，暂不接受新任务") if error.reason == "stopping" else t("该工具仍在运行，请勿重复提交"), type="warning")
            return False
        finally:
            self._starting = False
            for inputs in locked:
                inputs.unfreeze()
            for control, was_enabled in enabled:
                control.set_enabled(was_enabled)
            if self.client.has_socket_connection:
                from service.tools.tool_activity import active_count
                self.client.run_javascript("(window.top.calabashToolRuns || window.calabashToolRuns)?.setBusy(" + ("true" if active_count() else "false") + ")")

    def cancel(self):
        self.jobs.cancel()
        self.refresh()

    def refresh(self):
        if self.container.is_deleted:
            return
        self.container.clear()
        labels = {"queued": t("等待中"), "running": t("处理中"), "succeeded": t("已完成"), "failed": t("处理失败"), "cancelled": t("已取消")}
        with self.container:
            counts = self.jobs.counts
            completed = counts["succeeded"] + counts["failed"]
            ui.linear_progress(value=self.jobs.progress, show_value=False, size="3px").classes("w-full")
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(labels.get(self.jobs.status, t("正在取消"))).classes("text-xs text-gray-600")
                ui.label(f"{completed} / {len(self.jobs.jobs)} · " + t("完成 {succeeded} · 失败 {failed} · 未执行 {cancelled}", **{key: counts[key] for key in ("succeeded", "failed", "cancelled")})).classes("text-xs text-gray-500")
                if self.jobs.running:
                    if self.jobs.cancelling:
                        ui.label(t("正在取消，等待当前项结束")).classes("text-xs text-gray-500")
                    else:
                        ui.button(icon="stop", on_click=self.cancel).props("flat round dense").classes("tool-job-action").tooltip(t("取消"))
                elif self.handler and any(job.status == "failed" for job in self.jobs.jobs):
                    ui.button(icon="replay", on_click=lambda: self.run(retry_failed=True)).props("flat round dense").classes("tool-job-action").tooltip(t("重试失败项"))
            for index, job in enumerate(self.jobs.jobs, 1):
                with ui.row().classes("w-full items-center gap-2 flex-nowrap text-sm"):
                    name = Path(job.value).name if isinstance(job.value, (str, Path)) else str(index)
                    ui.label(name).classes("flex-1 min-w-0 break-all")
                    ui.label(labels[job.status]).classes("shrink-0 text-gray-500")
