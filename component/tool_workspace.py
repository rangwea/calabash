"""Persistent published-tool pages; refreshing tab chrome never rebuilds a tool."""

import inspect
from urllib.parse import quote
from uuid import uuid4
from weakref import WeakValueDictionary

from nicegui import ui

from component.action_button import action_button
from core.i18n import t
from service.tools import tool_activity
from service.tools.tool_service import _validate_tool_identity

WORKSPACES = WeakValueDictionary()


class _RetainedToolPage(ui.element):
    """Keep iframe viewport geometry stable while hidden, including its scroll state."""

    def _handle_visibility_change(self, visible):
        if not hasattr(self, '_classes'):
            return
        self.classes(add='' if visible else 'invisible pointer-events-none',
                     remove='invisible pointer-events-none' if visible else '')


class ToolWorkspace:
    def __init__(self, on_activate, on_list, on_repair=None, before_navigate=None, on_change=None, on_edit=None):
        self.on_activate, self.on_list = on_activate, on_list
        self.on_edit = on_edit
        self.on_change = on_change
        self.visible = False
        self.before_navigate = before_navigate
        self.on_repair = on_repair
        self.id = uuid4().hex
        WORKSPACES[self.id] = self
        self.items = {}
        self.active = None
        self.revisions = {}
        self.latest_revisions = {}
        self.closing = set()
        self.status = {}
        self.client = ui.context.client
        self.parent = ui.context.slot.parent
        self.parent.classes("relative")
        self.bar = ui.row().classes('app-workspace-tabs w-full min-w-0 shrink-0 flex-nowrap items-center gap-2 px-2 py-1 border-b border-gray-100 overflow-hidden')
        self.pages = _RetainedToolPage('div').classes('absolute inset-x-0 top-10 bottom-0 min-h-0 overflow-hidden')
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
                page = _RetainedToolPage('iframe').classes('absolute inset-0 w-full h-full border-0 min-h-0').props('data-published-tool')
                page._props.update(src=f'/tools/{quote(project)}/{quote(name)}?embedded=true&workspace={self.id}', title=tool.get('title') or name)
            self.items[key] = (tool.get('title') or name, page)
            self.revisions[key] = tool.get('revision')
        self.latest_revisions[key] = tool.get('revision')
        self.activate(key)

    def activate(self, key):
        if key not in self.items:
            return
        self.active = key
        self.visible = True
        for candidate, (_, page) in self.items.items():
            page.set_visibility(candidate == key)
        self.pages.set_visibility(True)
        self.render_tabs()
        # Rebuilding tab chrome must not leave the newly selected tab off-screen.
        # Scroll its own strip without stealing focus from the tool iframe.
        self.client.run_javascript(
            "requestAnimationFrame(() => document.querySelector('#c"
            + str(self.bar.id)
            + " .workspace-tab-active')?.scrollIntoView({block:'nearest', inline:'nearest'}));"
        )
        self.on_activate()

    async def request_activate(self, key):
        if self.before_navigate is None or await self.before_navigate():
            self.activate(key)

    async def request_resume(self):
        if self.items and (self.before_navigate is None or await self.before_navigate()):
            self.activate(self.active if self.active in self.items else next(reversed(self.items)))

    def hide(self):
        self.visible = False
        self.pages.set_visibility(False)
        self.render_tabs()

    def render_tabs(self):
        self.status = {key: tool_activity.is_tool_running(*key) for key in self.items}
        self.bar.clear()
        self.bar.set_visibility(self.visible and bool(self.items))
        with self.bar:
            with ui.row().classes('workspace-tab-strip flex-1 min-w-0 items-center gap-1 flex-nowrap overflow-x-auto'):
                for key, (title, _) in self.items.items():
                    with ui.row().classes('workspace-tab items-center gap-0 flex-nowrap shrink-0 ' + ('workspace-tab-active' if self.active == key else '')):
                        if tool_activity.is_tool_running(*key):
                            ui.spinner(size='12px', color='grey-6').tooltip(t('正在运行'))
                        ui.button(title, on_click=lambda _, target=key: self.request_activate(target), color=None).props('flat dense no-caps aria-pressed=' + str(self.active == key).lower()).classes('workspace-tab-button max-w-40 min-w-0 truncate').tooltip(title)
                        button, _ = action_button('close', t('关闭工具'), lambda _, target=key: self.close(target), compact=True)
                        if key in self.closing:
                            button.disable()

            with ui.row().classes('items-center gap-1 shrink-0 flex-nowrap'):
                changed = self.active in self.items and self.revisions.get(self.active) != self.latest_revisions.get(self.active)
                if changed:
                    ui.label(t('代码已更新，刷新后生效')).classes('text-xs text-amber-700 max-w-40 truncate hidden lg:block')
                if self.on_edit:
                    button, _ = action_button('chat', t('对话修改'), self.edit_active, text=True)
                    button.set_enabled(self.active in self.items and self.active not in self.closing)
                button, tip = action_button('refresh', t('刷新工具'), self.refresh_active)
                button.set_enabled(self.active in self.items and self.active not in self.closing)
                if changed:
                    tip.set_text(t('代码已更新，刷新后生效'))
                    button._props['aria-description'] = t('代码已更新，刷新后生效')
                    with button:
                        ui.element('span').props('aria-hidden=true').classes('absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-primary pointer-events-none')

    async def edit_active(self):
        key = self.active
        if not self.on_edit or key not in self.items or key in self.closing:
            return
        result = self.on_edit({'project': key[0], 'name': key[1], 'title': self.items[key][0]})
        if inspect.isawaitable(result):
            await result

    def update_tools(self, tools):
        revisions = {(tool['project'], tool['name']): tool.get('revision') for tool in tools}
        changed = False
        for key in self.items:
            current = revisions.get(key)
            if self.latest_revisions.get(key) != current:
                self.latest_revisions[key] = current
                changed = True
        if changed:
            self.render_tabs()

    async def refresh_active(self):
        key = self.active
        if key not in self.items or key in self.closing:
            return
        if tool_activity.is_tool_running(*key):
            ui.notify(t('工具正在执行，请等待任务结束后再刷新'), type='warning')
            return
        with self.parent, ui.dialog() as dialog, ui.card().classes('w-full max-w-md gap-3'):
            ui.label(t('刷新工具“{title}”？', title=self.items[key][0])).classes('text-base font-semibold')
            ui.label(t('刷新会重新加载工具，并清除尚未保存的界面输入。已保存的数据不受影响。')).classes('text-sm text-gray-500')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button(t('取消'), on_click=lambda: dialog.submit(False)).props('flat')
                ui.button(t('刷新工具'), on_click=lambda: dialog.submit(True))
        if not await dialog or key not in self.items or key in self.closing:
            return
        if tool_activity.is_tool_running(*key):
            ui.notify(t('工具正在执行，请等待任务结束后再刷新'), type='warning')
            return
        from service.tools.tool_service import get_tool_by_name
        metadata = get_tool_by_name(key[1], key[0])
        if not metadata:
            ui.notify(t('工具不可用，请检查工具列表或修复后再试'), type='warning')
            return
        _, frame = self.items[key]
        title = metadata.get('title') or key[1]
        self.items[key] = (title, frame)
        self.revisions[key] = self.latest_revisions[key] = metadata.get('revision')
        frame._props.update(src=f'/tools/{quote(key[0])}/{quote(key[1])}?embedded=true&workspace={self.id}&reload={uuid4().hex}', title=title)
        frame.update()
        self.render_tabs()

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
        self.revisions.pop(key, None)
        self.latest_revisions.pop(key, None)
        page.delete()
        self.closing.discard(key)
        tool_activity.finish_tool_stop(*key)
        if self.active == key:
            if self.items:
                fallback = next(reversed(self.items))
                if self.visible:
                    self.activate(fallback)
                else:
                    self.active = fallback
                    for candidate, (_, frame) in self.items.items():
                        frame.set_visibility(candidate == fallback)
            else:
                self.active = None
                was_visible = self.visible
                self.visible = False
                self.pages.set_visibility(False)
                if was_visible:
                    self.on_list()
        self.render_tabs()
        if self.on_change:
            self.on_change()

    def check_jobs(self):
        with self.parent:
            for key in tuple(self.closing):
                if not tool_activity.is_tool_running(*key):
                    self.remove(key)
            status = {key: tool_activity.is_tool_running(*key) for key in self.items}
            if status != self.status:
                self.status = status
                self.render_tabs()
                if self.on_change:
                    self.on_change()

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
