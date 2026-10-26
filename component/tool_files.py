"""Reusable desktop file selection with batch-safe draft state."""

from nicegui import ui

from component.file_access import choose_path, choose_paths
from core.i18n import t
from service.files import tool_inputs
from service.files.tool_input_selection import ToolInputSelection


def _size(value):
    if value is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024


class ToolFileInput:
    def __init__(self):
        context = getattr(ui.context.client, "calabash_input_context", None)
        self._selection = ToolInputSelection(tool_inputs.current_inputs(), context=context)
        self._picking = False
        self._controls = []
        self.render = ui.refreshable(self._render)
        self.render()

    @property
    def paths(self):
        try:
            return self._selection.paths()
        except ValueError as error:
            raise ValueError(t("文件已变化或不可访问，请重新选择")) from error

    @property
    def files(self):
        return self._selection.files()

    @property
    def frozen(self):
        return self._selection.locked

    def freeze(self):
        snapshot = tuple(self.paths)
        self.set_enabled(False)
        return snapshot

    def unfreeze(self):
        self.set_enabled(True)

    def set_enabled(self, enabled):
        self._selection.set_locked(not enabled)
        self._update_controls()

    def _update_controls(self):
        for button, needs_files in self._controls:
            button.set_enabled(not self.frozen and not self._picking and (not needs_files or bool(len(self._selection))))
        self._locked_label.set_visibility(self.frozen)

    def refresh(self):
        self.render.refresh()

    def add_paths(self, paths):
        count = self._selection.add(paths)
        if count:
            self.refresh()
        return count

    def remove(self, key):
        changed = self._selection.remove(key)
        if changed:
            self.refresh()
        return changed

    def clear(self):
        changed = self._selection.clear()
        if changed:
            self.refresh()
        return changed

    async def add_files(self):
        await self._pick()

    async def reselect(self, key):
        await self._pick(key)

    async def _pick(self, key=None):
        if self.frozen or self._picking:
            return
        revision = self._selection.revision
        self._picking = True
        self._update_controls()
        try:
            result = await choose_paths() if key is None else await choose_path()
            if not result or self.frozen or revision != self._selection.revision:
                return
            changed = self._selection.add(result) if key is None else self._selection.replace(key, result)
            if changed:
                self.refresh()
        except (OSError, RuntimeError, TimeoutError):
            ui.notify(t("无法选择文件，请重试"), type="warning")
        finally:
            self._picking = False
            self._update_controls()

    def _button(self, icon, label, callback, needs_files=False):
        button = ui.button(icon=icon, on_click=callback).props("flat dense round").tooltip(label)
        button.props.update({"aria-label": label})
        self._controls.append((button, needs_files))
        return button

    def _render(self):
        self._controls = []
        items = self.files
        labels = {"ready": t("可用"), "changed": t("文件已变更"), "missing": t("文件不存在"), "denied": t("无访问权限"), "expired": t("引用已失效"), "not_file": t("不是普通文件")}
        with ui.column().classes("w-full min-w-0 gap-1"):
            with ui.row().classes("w-full min-w-0 items-center gap-2 flex-wrap"):
                self._button("attach_file", t("追加文件"), self.add_files)
                ui.label(t("已选择 {count} 个文件", count=len(items))).classes("text-xs text-gray-500")
                self._button("playlist_remove", t("清空列表"), self.clear, True)
                ui.button(icon="refresh", on_click=self.refresh).props("flat dense round").tooltip(t("检查文件状态"))
                self._locked_label = ui.label(t("执行中，输入已锁定")).classes("text-xs text-gray-500")
            for item in items:
                with ui.row().classes("w-full min-w-0 items-center gap-2 flex-nowrap"):
                    ui.icon("description").classes("text-gray-400 shrink-0")
                    with ui.column().classes("flex-1 min-w-0 gap-0"):
                        ui.label(item["name"]).classes("text-sm w-full truncate").tooltip(item["name"])
                        with ui.row().classes("gap-2 items-center flex-wrap"):
                            ui.label(f"{item['type'] or '-'} · {_size(item['size'])}").classes("text-xs text-gray-500")
                            ui.label(labels[item["status"]]).classes("text-xs " + ("text-gray-500" if item["status"] == "ready" else "text-negative"))
                    self._button("file_open", t("重新选择 {name}", name=item["name"]), lambda key=item["key"]: self.reselect(key))
                    self._button("close", t("移除 {name}", name=item["name"]), lambda key=item["key"]: self.remove(key))
        self._update_controls()
