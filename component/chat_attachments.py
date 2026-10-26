"""Compact local attachment controls for the conversation composer."""

from nicegui import ui

from component.file_access import choose_chat_files
from core.i18n import t
from core.logger import get_logger
from service.files import conversation_files as files

logger = get_logger(__name__)


class NativeFileDrop(ui.element, component="native_file_drop.js"):
    """Mount native event forwarding with the composer, not a delayed timer."""

    def __init__(self):
        super().__init__()
        self.classes("nicegui-column")


def file_size(size):
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def attachment_error(code):
    if code == "picker_failed":
        return t("无法打开系统选择器，请重启应用后重试")
    if code == "limit":
        return t("每条消息最多添加 20 个文件")
    if code == "upload_limit":
        return t("浏览器上传的单个文件不能超过 50 MB")
    if code == "deleted":
        return t("对话已删除，请创建新对话")
    if code == "invalid_selection":
        return t("文件选择已过期，请重新选择")
    return t("无法添加文件，请检查文件是否存在及访问权限")


def render_file(item, chat_id, *, remove=None):
    status = files.check(chat_id, item["id"])
    with ui.row().classes("chat-attachment items-center flex-nowrap gap-2 min-w-0"):
        ui.icon("description").classes("text-base shrink-0 text-gray-400")
        with ui.column().classes("min-w-0 flex-1 gap-0"):
            ui.label(item["name"]).classes("truncate w-full text-xs text-gray-700").tooltip(item["name"])
            details = file_size(item["size"])
            extension = item["name"].rsplit(".", 1)[-1].upper() if "." in item["name"] else "FILE"
            details = f"{extension[:12]} · {details}"
            if item["source"] == "upload":
                details += " · " + t("上传副本")
            if status != "ready":
                details += " · " + (t("文件已变化，请重新选择") if status == "changed" else t("文件不可访问"))
            ui.label(details).classes("text-xs text-gray-400 break-words")
        if remove:
            ui.button(icon="close", on_click=remove).props("flat dense round").tooltip(t("移除附件"))


class ChatAttachments:
    def __init__(self, chat_id, on_change):
        self.chat_id = chat_id
        self.on_change = on_change
        self.busy = False
        self.render = ui.refreshable(self._render)
        ui.add_css("""
            .calabash-chat .chat-attachment { border: 1px solid #e5e7eb; border-radius: 6px;
                padding: 7px 9px; width: 220px; max-width: 100%; background: #fafbfc; }
            .calabash-chat .chat-file-list { display: flex; flex-wrap: wrap; gap: 6px; width: 100%; min-width: 0; }
            .calabash-chat .chat-compose.file-hover { outline: 2px solid #7796b8; background: #f6f9fc; }
        """)

    def _render(self):
        with ui.element("div").classes("chat-file-list"):
            for item in files.list_files(self.chat_id(), pending=True):
                def remove(_, file_id=item["id"]):
                    files.remove_pending(self.chat_id(), file_id)
                    self.render.refresh()
                render_file(item, self.chat_id(), remove=remove)

    def ids(self):
        return [item["id"] for item in files.list_files(self.chat_id(), pending=True)]

    def notify_error(self, error):
        ui.notify(attachment_error(str(error)), type="warning")

    def consume(self, chat_id, ticket):
        try:
            results = files.consume_selection(chat_id, ticket)
            for error in {result["error"] for result in results if "error" in result}:
                self.notify_error(error)
            self.on_change(chat_id)
        except (ValueError, OSError) as error:
            self.notify_error(error)
        self.render.refresh()

    async def select(self):
        if self.busy:
            ui.notify(t("文件正在上传，请稍后发送"), type="info")
            return
        chat_id = self.chat_id()
        result = await choose_chat_files()
        if result and result.get("browser"):
            self.upload_dialog(chat_id)
        elif result and result.get("ticket"):
            self.consume(chat_id, result["ticket"])
        elif result and result.get("error"):
            logger.warning(f"Native file picker failed: {result.get('detail', result['error'])}")
            self.notify_error(result["error"])

    def upload_dialog(self, chat_id):
        async def uploaded(event):
            try:
                for file in event.files[:files.MAX_FILES]:
                    try:
                        await files.store_upload(chat_id, file)
                        self.on_change(chat_id)
                    except (ValueError, OSError) as error:
                        self.notify_error(error)
                if len(event.files) > files.MAX_FILES:
                    self.notify_error("limit")
            finally:
                self.busy = False
                uploader.reset()
                self.render.refresh()

        def begin():
            self.busy = True

        def failed():
            self.busy = False
            ui.notify(t("文件上传失败，请重试"), type="warning")

        with ui.dialog() as dialog, ui.card().classes("w-full max-w-lg gap-3"):
            ui.label(t("添加文件")).classes("text-base font-medium")
            ui.label(t("浏览器将上传文件副本，不会修改原文件")).classes("text-xs text-gray-500")
            uploader = ui.upload(multiple=True, auto_upload=True, max_files=files.MAX_FILES,
                                 max_file_size=files.UPLOAD_LIMIT, max_total_size=files.UPLOAD_LIMIT * files.MAX_FILES,
                                 on_begin_upload=begin, on_multi_upload=uploaded,
                                 on_rejected=lambda: self.notify_error("upload_limit"), label=t("选择或拖入文件")).classes("w-full")
            uploader.on("failed", failed)
            ui.button(t("完成"), on_click=dialog.close).props("flat")
        dialog.open()

    def connect_drop(self, compose):
        def dropped(event):
            data = event.args
            if data.get("ticket"):
                self.consume(self.chat_id(), data["ticket"])
            elif data.get("error"):
                self.notify_error(data["error"])

        compose.on("selection", dropped)

    def button(self):
        ui.button(icon="attach_file", on_click=self.select).props("flat dense round").tooltip(t("添加文件"))
