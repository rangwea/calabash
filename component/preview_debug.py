"""Host-owned consent dialogs for preview diagnosis and each interaction."""

from urllib.parse import urlsplit

from nicegui import ui

from component.action_button import action_button
from core.i18n import t
from service.chat import model_providers
from service.tools import preview_debug


class PreviewDebugControl:
    def __init__(self, chat_id, get_url):
        self.chat_id, self.get_url = chat_id, get_url
        self.client = ui.context.client
        self.button, self.tip = action_button('inspect', t('诊断与验收'), self.toggle)
        self.dialog = ui.dialog()

    async def toggle(self):
        try:
            session = preview_debug.current(self.chat_id, self.get_url())
            if session.approved_at:
                session.revoke()
                ui.notify(t('已关闭预览诊断授权'))
                return
            provider, model, connection = model_providers.active()
            with self.client, self.dialog, ui.card().classes('w-full max-w-lg gap-3'):
                ui.label(t('授权当前预览诊断？')).classes('text-lg font-semibold')
                ui.label(f"{model} · {urlsplit(connection['base_url']).hostname or provider}").classes('text-sm')
                ui.label(t('Agent 可读取当前预览的可见文字、控件、前端错误和媒体状态，可能涉及业务信息。不会读取输入框值或自动附加页面。授权十分钟内有效，刷新、断开连接或修改源码后失效。')).classes('text-sm')
                ui.label(t('每次点击或输入都会单独确认；自定义按钮可能写入、删除或导出文件，请核对后再允许。')).classes('text-sm')
                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button(t('取消'), on_click=lambda: self.dialog.submit(False)).props('flat no-caps')
                    ui.button(t('允许诊断'), on_click=lambda: self.dialog.submit(True)).props('unelevated no-caps')
            allowed = await self.dialog
            self.dialog.clear()
            if allowed:
                session.grant(self.confirm_action)
                ui.notify(t('已授权，可在对话中要求 Agent 检查当前预览'))
        except (ValueError, OSError):
            self.dialog.clear()
            ui.notify(t('请打开唯一的当前预览；源码变更后先手动刷新，再授权诊断'), type='warning')

    async def confirm_action(self, request):
        with self.client, ui.dialog() as dialog, ui.card().classes('w-full max-w-lg gap-3'):
            ui.label(t('确认预览操作')).classes('text-lg font-semibold')
            ui.label(request['tool']).classes('text-sm font-medium')
            ui.label(t('操作：{action}；控件：{label}', action=request['action'], label=request['label'])).classes('text-sm break-all')
            if request['action'] == 'fill':
                ui.label(t('输入：{value}', value=request['value'])).classes('text-sm break-all')
            ui.label(t('目的：{reason}', reason=request['reason'])).classes('text-sm break-all')
            ui.label(t('此操作可能触发真实业务写入、删除或导出。仅在确认本次操作及其影响后允许；不代表后续操作也获授权。')).classes('text-sm')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button(t('拒绝'), on_click=lambda: dialog.submit(False)).props('flat no-caps')
                ui.button(t('允许本次操作'), on_click=lambda: dialog.submit(True)).props('unelevated no-caps')
        try:
            return bool(await dialog)
        finally:
            dialog.close()
            dialog.delete()
