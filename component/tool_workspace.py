"""Persistent published-tool pages; refreshing tab chrome never rebuilds a tool."""

from urllib.parse import quote
from uuid import uuid4
from weakref import WeakValueDictionary

from nicegui import ui

from component.action_button import action_button
from core.i18n import t
from service.tools import tool_activity
from service.tools.tool_service import _validate_tool_identity

WORKSPACES = WeakValueDictionary()


class ToolWorkspace:
    def __init__(self, on_activate, on_list, on_repair=None):
        self.on_activate, self.on_list = on_activate, on_list
        self.on_repair = on_repair
        self.id = uuid4().hex
        WORKSPACES[self.id] = self
        self.items = {}
        self.active = None
        self.closing = set()
        self.status = {}
        self.client = ui.context.client
        self.parent = ui.context.slot.parent
        self.bar = ui.row().classes('w-full min-w-0 shrink-0 flex-nowrap items-center gap-2 px-2 py-1 border-b border-gray-100 overflow-hidden')
        self.pages = ui.column().classes('w-full flex-1 min-h-0 gap-0 overflow-hidden')
        self.bar.set_visibility(False)
        self.pages.set_visibility(False)
        self.client.on_delete(self.dispose)
        ui.timer(0.3, self.check_jobs)

    def open(self, tool):
        project, name = tool['project'], tool['name']
        _validate_tool_identity(project, name)
        key = (project, name)
        if key not in self.items:
            with self.pages:
                page = ui.element('iframe').classes('w-full h-full border-0 flex-1 min-h-0').props('data-published-tool')
                page._props.update(src=f'/tools/{quote(project)}/{quote(name)}?embedded=true&workspace={self.id}', title=tool.get('title') or name)
            self.items[key] = (tool.get('title') or name, page)
        self.activate(key)

    def activate(self, key):
        if key not in self.items:
            return
        self.active = key
        for candidate, (_, page) in self.items.items():
            page.set_visibility(candidate == key)
        self.pages.set_visibility(True)
        self.render_tabs()
        self.on_activate()

    def hide(self):
        self.active = None
        self.pages.set_visibility(False)
        self.render_tabs()

    def render_tabs(self):
        self.status = {key: tool_activity.is_tool_running(*key) for key in self.items}
        self.bar.clear()
        self.bar.set_visibility(bool(self.items))
        with self.bar:
            entry, _ = action_button('grid', t('工具列表'), self.on_list, text=True)
            entry.classes('bg-gray-50 border border-gray-200')
            ui.element('div').classes('h-5 w-px bg-gray-200 shrink-0 mx-1')
            with ui.row().classes('flex-1 min-w-0 items-center gap-1 flex-nowrap overflow-x-auto'):
                for key, (title, _) in self.items.items():
                    with ui.row().classes('items-center gap-0 flex-nowrap shrink-0 rounded-md ' + ('bg-gray-100' if self.active == key else '')):
                        if tool_activity.is_tool_running(*key):
                            ui.spinner(size='12px', color='grey-6').tooltip(t('正在运行'))
                        ui.button(title, on_click=lambda _, target=key: self.activate(target), color=None).props('flat dense no-caps').classes('max-w-48 truncate text-xs text-gray-600').tooltip('/'.join(key))
                        button, _ = action_button('close', t('关闭工具'), lambda _, target=key: self.close(target), compact=True)
                        if key in self.closing:
                            button.disable()

    async def close(self, key):
        if key not in self.items or key in self.closing:
            return
        if tool_activity.is_tool_running(*key):
            with self.parent, ui.dialog() as dialog, ui.card().classes('w-full max-w-md gap-3'):
                ui.label(t('工具仍在运行')).classes('text-lg font-semibold')
                ui.label(t('可以继续等待，或安全取消。当前文件处理完成后才会关闭工具。')).classes('text-sm text-gray-500')
                with ui.row().classes('w-full justify-end'):
                    ui.button(t('继续等待'), on_click=lambda: dialog.submit(False)).props('flat no-caps')
                    ui.button(t('安全取消后关闭'), on_click=lambda: dialog.submit(True)).props('unelevated no-caps')
            if not await dialog or key not in self.items:
                return
            self.closing.add(key)
            tool_activity.request_tool_stop(*key)
            self.render_tabs()
            self.check_jobs()
            return
        self.remove(key)

    def remove(self, key):
        _, page = self.items.pop(key)
        page.delete()
        self.closing.discard(key)
        tool_activity.finish_tool_stop(*key)
        if self.active == key:
            if self.items:
                self.activate(next(reversed(self.items)))
            else:
                self.active = None
                self.pages.set_visibility(False)
                self.on_list()
        self.render_tabs()

    def check_jobs(self):
        with self.parent:
            for key in tuple(self.closing):
                if not tool_activity.is_tool_running(*key):
                    self.remove(key)
            status = {key: tool_activity.is_tool_running(*key) for key in self.items}
            if status != self.status:
                self.status = status
                self.render_tabs()

    def dispose(self):
        WORKSPACES.pop(self.id, None)
        for key in self.closing:
            tool_activity.finish_tool_stop(*key)

    def repair(self, report_id):
        from service.tools.tool_repairs import get
        report = get(report_id)
        if (report['project'], report['name']) in self.items and self.on_repair:
            with self.parent:
                self.on_repair(report['chat_id'])
