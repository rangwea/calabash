"""Desktop AI conversation workspace."""

import asyncio
import json
from uuid import uuid4

import httpx
from nicegui import ui

from component.action_button import action_button as _toolbar_button
from component.chat_attachments import ChatAttachments, NativeFileDrop, render_file
from core.i18n import t
from core.logger import get_logger
from service.chat import ai_chat as chat
from service.chat import model_providers

_COMPOSER_KEYDOWN_JS = """(e) => {
    if (e.target.closest?.('.chat-compose')?.dataset?.uploading === 'true') return;
    if (e.shiftKey || e.repeat || e.isComposing || e.keyCode === 229 ||
        e.target.calabashComposing ||
        (e.target.calabashCompositionEnded !== undefined &&
         performance.now() - e.target.calabashCompositionEnded < 50)) return;
    e.preventDefault();
    emit();
}"""

ACTION_LABELS = {
    "generating_tool": "正在生成工具代码…",
    "thinking": "正在思考",
    "resuming": "正在恢复生成进度…",
    "write_file": "编辑工具草稿",
    "edit_file": "编辑工具草稿",
    "read_file": "读取工具草稿",
    "stage_tool": "读取工具代码",
    "deliver_draft": "处理工具草稿",
    "write_todos": "更新执行计划",
    "list_tools": "检查现有工具",
    "read_tool": "读取工具代码",
    "read_tool_logs": "查询当前工具日志",
    "validate_tool": "校验工具代码",
    "write_tool": "保存工具文件",
    "preview_tool": "准备工具预览",
    "list_attachments": "检查附件",
    "read_attachment": "读取附件",
}
logger = get_logger(__name__)


def render_ai_chat(chat_id=None, on_change=None):
    """Keep each conversation's UI and generation task alive while switching."""
    host = ui.column().classes("w-full h-full min-h-0 gap-0")
    sessions = {}
    active = {"id": None}

    def changed(_chat_id):
        # A background completion refreshes history without selecting that chat.
        if on_change and active["id"]:
            on_change(active["id"])

    def switch(target=None):
        target = target or uuid4().hex
        if active["id"] in sessions:
            sessions[active["id"]].set_visibility(False)
        active["id"] = target
        if target not in sessions:
            with host:
                pane = ui.column().classes("w-full h-full min-h-0 gap-0").props(
                    f'data-chat-session="{target}"'
                )
                sessions[target] = pane
                with pane:
                    _render_chat_session(target, on_change=changed)
        sessions[target].set_visibility(True)
        changed(target)

    switch(chat_id)
    return switch


def _render_chat_session(chat_id=None, on_change=None):
    client = ui.context.client
    if not hasattr(client, "calabash_running_chats"):
        client.calabash_running_chats = set()
    generation = {"running": False}
    ui.add_css("""
        .calabash-chat .chat-repair-retry.q-btn {
            min-height: 30px; padding: 4px 8px; border-radius: 6px;
            font-size: 13px; font-weight: 500; color: var(--app-muted); letter-spacing: 0;
        }
        .calabash-chat .chat-repair-retry.q-btn .q-icon {
            width: 16px; height: 16px; font-size: 16px; margin-right: 6px;
        }
        .calabash-chat { background: var(--app-surface); }
        .calabash-chat .q-btn--round {
            width: 30px; height: 30px; min-width: 30px; min-height: 30px;
            padding: 0; border-radius: 6px; color: var(--app-icon);
        }
        .calabash-chat .q-btn--round .q-icon { font-size: 18px; }
        .calabash-chat .q-btn--round:hover { background: var(--app-hover); color: var(--app-text); }
        .calabash-chat .chat-send { background: var(--app-primary) !important; color: white !important; }
        .calabash-chat .chat-send:hover { background: var(--app-primary-hover) !important; }
        .calabash-chat .chat-model { padding: 4px 7px; font-size: 12px; color: var(--app-icon); }
        .calabash-chat .chat-model .q-icon { font-size: 16px; margin-right: 6px; }
        .calabash-chat .preview-body > .nicegui-refreshable { width: 100%; height: 100%; }
        .calabash-chat .chat-history { background: var(--app-sidebar); }
        .calabash-chat .chat-session { border-radius: 6px; min-height: 32px; }
        .calabash-chat .chat-session .q-btn__content {
            display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
            text-align: left; font-size: 12px;
        }
        .calabash-chat .chat-user {
            align-self: flex-end; max-width: 85%; background: var(--app-primary-light);
            border-radius: 8px; padding: 10px 14px; color: var(--app-text);
        }
        .calabash-chat .chat-message { font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; }
        .calabash-chat .chat-message { color: var(--app-text); line-height: 1.6; }
        .calabash-chat .chat-message h1,
        .calabash-chat .chat-message h2,
        .calabash-chat .chat-message h3 { font-size: 15px; line-height: 1.5; margin: 18px 0 8px; font-weight: 600; }
        .calabash-chat .chat-message ul,
        .calabash-chat .chat-message ol { padding-left: 22px; margin: 8px 0 14px; }
        .calabash-chat .chat-message li { margin: 4px 0; }
        .calabash-chat .chat-message :not(pre) > code { font-size: 12px; background: var(--app-background); padding: 2px 5px; border-radius: 4px; }
        .calabash-chat .chat-message a { color: var(--app-primary); text-decoration: none; border-bottom: 1px solid var(--app-primary-soft); }
        .calabash-chat .chat-message blockquote { border-left: 2px solid var(--app-border); padding-left: 12px; margin: 12px 0; color: var(--app-muted); }
        .calabash-chat .chat-process { border: 0; border-radius: 0; box-shadow: none; margin: 8px 0; }
        .calabash-chat .chat-process .q-item { min-height: 30px; padding: 0; font-size: 12px; color: var(--app-muted); }
        .calabash-chat .chat-process .q-expansion-item__content { padding: 8px 0 8px 12px; border-left: 1px solid var(--app-border); }
        .calabash-chat .chat-process .chat-message { font-size: 12px; color: var(--app-muted); }
        .calabash-chat .chat-message p { margin: 0 0 12px; }
        .calabash-chat .chat-message p:last-child { margin-bottom: 0; }
        .calabash-chat .chat-message pre { max-width: 100%; overflow-x: auto; border-radius: 6px; }
        .calabash-chat .chat-compose {
            border: 1px solid var(--app-border-strong); border-radius: 8px; background: var(--app-surface);
            box-shadow: 0 2px 6px rgb(28 42 62 / 4%); padding: 10px 12px;
        }
        .calabash-chat .chat-compose:focus-within { border-color: var(--app-primary); box-shadow: 0 0 0 1px var(--app-primary); }
        .calabash-chat .chat-compose .q-field__control { background: transparent; padding: 0; }
        .calabash-chat .chat-compose .q-field__control:before,
        .calabash-chat .chat-compose .q-field__control:after { display: none; }
        .calabash-chat .chat-compose textarea {
            font-size: 14px; line-height: 1.6; min-height: 54px; max-height: 180px;
            padding: 4px 2px; overflow-y: auto !important;
        }
        .calabash-chat .chat-compose .q-field__bottom { display: none; }
        @media (max-width: 1000px) { .calabash-chat .chat-history { width: 156px; } }
    """)
    selected = {"id": chat_id or uuid4().hex}
    messages = chat.read_chat(chat_id) if chat_id else []
    task = None
    preview_state = {"url": "", "revision": 0, "mounted_url": None}
    publishing = {"busy": False}
    failure = {"message": chat.read_failure(selected["id"])}
    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), {})
    if not failure["message"] and last_user.get("agent_run_id") and not last_user.get("agent_completed") and not last_user.get("repair_id"):
        failure["message"] = t("生成尚未完成，进度已保存；点击继续生成")

    def files_changed(chat_id):
        if on_change and chat_id == selected["id"]:
            on_change(chat_id)

    attachments = ChatAttachments(lambda: selected["id"], files_changed)

    def set_preview_visible(visible):
        save_preview_button.set_enabled(bool(preview_state["url"]) and not publishing["busy"])
        refresh_preview_button.set_enabled(bool(preview_state["url"]))
        open_preview_button.set_enabled(bool(preview_state["url"]))
        chat_root.props('data-preview-open=' + str(bool(visible)).lower())
        preview_panel.set_visibility(visible)
        preview_divider.set_visibility(visible)
        preview_toggle._props["aria-pressed"] = visible
        preview_toggle._props["aria-label"] = t("关闭预览") if visible else t("打开预览")
        preview_tip.set_text(t("关闭预览") if visible else t("打开预览"))
        preview_toggle.update()

    def toggle_preview():
        if preview_panel.visible:
            set_preview_visible(False)
        elif preview_state["url"]:
            if preview_state["mounted_url"] == preview_state["url"]:
                set_preview_visible(True)
            else:
                show_preview({"url": preview_state["url"]})
        else:
            ui.notify(t("生成工具后即可打开预览"), type="info")

    def show_preview(result):
        from service.tools.tool_activity import active_count
        if active_count():
            ui.notify(t("工具仍在运行，请等待完成或安全取消后刷新预览"), type="warning")
            return
        url = result.get("preview_url") or result.get("url", "")
        if not url.startswith("/preview/") or url.startswith("//"):
            return
        preview_state["url"] = url
        chat.remember_preview(selected["id"], url)
        preview_state["revision"] += 1
        set_preview_visible(True)
        preview_content.refresh()

    async def save_preview_tool():
        from service.tools import preview_publish
        from service.tools.tool_activity import ToolBusyError
        if publishing["busy"]:
            return
        publishing["busy"] = True
        save_preview_button.disable()
        try:
            snapshot = preview_publish.prepare(selected["id"], preview_state["url"])
            if snapshot.revision is not None:
                with preview_panel, ui.dialog() as dialog, ui.card().classes("w-full max-w-md gap-3"):
                    ui.label(t("覆盖已有工具？")).classes("text-lg font-semibold")
                    ui.label(t("工具 {tool} 已存在，是否用当前预览版本覆盖？", tool=f"{snapshot.project}/{snapshot.name}"))
                    with ui.row().classes("w-full justify-end"):
                        ui.button(t("取消"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
                        ui.button(t("确认覆盖"), on_click=lambda: dialog.submit(True)).props("unelevated no-caps")
                if not await dialog:
                    return
            if preview_state["url"] != snapshot.url:
                raise ValueError('preview_changed')
            preview_publish.save(snapshot, overwrite=snapshot.revision is not None)
            ui.notify(t("已保存到工具列表"), type="positive")
            if on_change:
                on_change(selected["id"])
        except ToolBusyError:
            ui.notify(t("工具正在运行，暂时无法覆盖"), type="warning")
        except (OSError, ValueError, SyntaxError):
            logger.exception("Unable to publish selected preview")
            ui.notify(t("无法保存预览，请刷新后重试；预览或目标工具可能已更改或过期"), type="warning")
        finally:
            publishing["busy"] = False
            save_preview_button.set_enabled(bool(preview_state["url"]))

    def assistant_markdown(content):
        element = ui.markdown(content).classes("chat-message w-full")
        element.on(
            "click",
            lambda event: show_preview({"url": event.args["url"]}),
            js_handler="""(event) => {
                const link = event.target.closest('a');
                if (!link) return;
                const url = new URL(link.getAttribute('href'), window.location.href);
                if (url.origin !== window.location.origin || !url.pathname.startsWith('/preview/')) return;
                event.preventDefault();
                event.stopPropagation();
                emit({url: url.pathname + url.search});
            }""",
        )
        return element

    def restore_preview():
        set_preview_visible(False)
        preview_state["url"] = chat.remembered_preview(selected["id"])
        if preview_state["url"]:
            return  # Opening the panel is an explicit run, including after repair.
        for message in reversed(messages):
            if message.get("role") != "tool":
                continue
            try:
                result = json.loads(message["content"])
            except (ValueError, TypeError):
                continue
            if isinstance(result, dict) and result.get("success") and str(result.get("preview_url", "")).startswith("/preview/"):
                if result.get("requires_manual_run"):
                    preview_state["url"] = result["preview_url"]
                    break
                show_preview(result)
                break

    @ui.refreshable
    def preview_content():
        if preview_state["url"] and preview_panel.visible:
            separator = "&" if "?" in preview_state["url"] else "?"
            url = f"{preview_state['url']}{separator}embedded=1&revision={preview_state['revision']}"
            frame = ui.element("iframe").classes("w-full h-full border-0 bg-white")
            frame._props.update(src=url, title=t("工具预览"))
            preview_state["mounted_url"] = preview_state["url"]
        else:
            with ui.column().classes("w-full h-full items-center justify-center gap-2 p-6"):
                ui.icon("preview").classes("text-2xl text-gray-300")
                ui.label(t("暂无工具预览")).classes("text-sm text-gray-500")

    def connection():
        ui.notify(t("请在右上角设置中的「模型配置」添加服务商与模型"), type="info")

    @ui.refreshable
    def timeline():
        for message in messages:
            if message.get("role") == "system" and message.get("content", "").startswith("当前引用工具："):
                reference = json.loads(message["content"].split("\n", 1)[0].removeprefix("当前引用工具："))
                with ui.row().classes("items-center gap-2 px-3 py-2 bg-gray-50 rounded-md border border-gray-100"):
                    ui.icon("code").classes("text-base text-gray-500")
                    ui.label(f"{reference['project']}/{reference['name']}").classes("text-xs text-gray-600")
        if not messages:
            with ui.column().classes("w-full items-center justify-center py-24 gap-2"):
                ui.label(t("从一个想法开始")).classes("text-xl font-semibold text-gray-800")
                ui.label(t("今天想做什么工具？")).classes("text-sm text-gray-400")
        pending_steps = []
        def render_steps():
            if not pending_steps:
                return
            with ui.expansion(t("执行过程 · {count} 个步骤", count=len(pending_steps)), icon="done", value=False).props("dense").classes("chat-process w-full"):
                for step in pending_steps:
                    for call in step.get("tool_calls", []):
                        name = call.get("function", {}).get("name", "")
                        ui.label(t(ACTION_LABELS.get(name, "处理工具"))).classes("text-xs text-gray-500 py-1")
                    if step.get("content"):
                        assistant_markdown(step["content"])
            pending_steps.clear()

        for message in messages:
            if message["role"] == "assistant" and message.get("tool_calls"):
                pending_steps.append(message)
                continue
            if message["role"] in {"user", "assistant"} and message.get("content"):
                render_steps()
                if message["role"] == "user":
                    with ui.column().classes("w-full items-end gap-0 py-4"):
                        ui.markdown(message["content"]).classes("chat-user chat-message")
                        if message.get("id"):
                            from service.files.conversation_files import for_message
                            with ui.element("div").classes("chat-file-list justify-end pt-2"):
                                for item in for_message(selected["id"], message["id"]):
                                    render_file(item, selected["id"])
                else:
                    with ui.column().classes("w-full min-w-0 gap-2 pt-2 pb-5"):
                        assistant_markdown(message["content"])
        render_steps()
        for message in reversed(messages):
            if message.get("role") == "tool":
                try:
                    result = json.loads(message["content"])
                except (ValueError, TypeError):
                    continue
                if isinstance(result, dict) and result.get("requires_manual_run"):
                    if message.get("repair_completed") and not generation["running"] and not failure["message"]:
                        ui.button(t("修改已保存，手动重试运行"), icon="o_restart_alt", on_click=lambda result=result: show_preview(result)).props("flat dense no-caps").classes("chat-repair-retry")
                        ui.label(t("尚未运行验证；保存修改不代表问题已解决。")).classes("text-xs text-gray-500")
                    break
        if failure["message"]:
            with ui.row().classes("w-full items-center gap-2 px-3 py-2 bg-red-50 rounded-md"):
                ui.icon("error_outline").classes("text-red-500 text-base")
                ui.label(failure["message"]).classes("flex-1 min-w-0 text-xs text-red-700 break-words")
                last_user = next((m for m in reversed(messages) if m.get("role") == "user"), {})
                if last_user.get("repair_id"):
                    from component.tool_repair import RepairFeedback
                    from service.tools.tool_repairs import get
                    report = get(last_user["repair_id"])
                    feedback = RepairFeedback(report["project"], report["name"], show_retry=False, preview_key=report["preview_key"], context=report["context"])
                    feedback.report_id = report["id"]
                    feedback.container.set_visibility(True)
                else:
                    ui.button(t("继续生成"), icon="o_play_arrow", on_click=retry, color=None).props("flat dense no-caps").classes("text-xs text-gray-500").tooltip(t("继续生成"))

    async def generate():
        # asyncio tasks do not inherit NiceGUI's active slot stack.
        with feed:
            await generate_in_slot()

    async def generate_in_slot(repair=None):
        generation["running"] = True
        client.calabash_running_chats.add(selected["id"])
        if on_change:
            on_change(selected["id"])
        completed = False
        failure["message"] = ""
        timeline.refresh()
        chat.save_failure(selected["id"], "")
        send.disable()
        stop.enable()
        stop.set_visibility(True)
        partial = ""
        original_count = len(messages)
        with feed:
            answer = assistant_markdown("").classes("py-5")
            activity = ui.label(t("正在连接模型…")).classes("text-xs text-gray-400")
        try:
            response = chat.respond(messages, chat_id=selected["id"], repair=repair) if repair else chat.respond(messages, chat_id=selected["id"])
            async for kind, value in response:
                if kind == "text":
                    partial += value
                    answer.set_content(partial)
                elif kind == "preview":
                    show_preview(value)
                elif kind == "manual_preview":
                    activity.set_text(t("正在处理工具…"))
                else:
                    activity.set_text(t(ACTION_LABELS.get(value, "正在处理工具…")))
                    if partial:
                        partial += "\n\n"
            completed = True
        except asyncio.CancelledError:
            # Completed graph turns survive errors and cancellation for safe resume.
            failure["message"] = t("生成已暂停，进度已保存；点击继续生成")
            ui.notify(t("已停止"))
        except TimeoutError:
            failure["message"] = t("模型响应超时，请重试或选择其他模型")
            ui.notify(failure["message"], type="negative")
        except (ValueError, httpx.HTTPError) as error:
            failure["message"] = str(error) if isinstance(error, ValueError) else t("网络连接失败，请重试")
            ui.notify(failure["message"], type="negative")
        except Exception as error:  # noqa: BLE001 - restore controls after unexpected response failures
            logger.error(f"Chat response failed ({type(error).__name__})")
            failure["message"] = t("回复失败，请重试或新建对话")
            ui.notify(failure["message"], type="negative")
        finally:
            generation["running"] = False
            client.calabash_running_chats.discard(selected["id"])
            if completed:
                for message in messages[original_count:]:
                    if message.get("role") == "tool":
                        try:
                            result = json.loads(message["content"])
                        except (ValueError, TypeError):
                            continue
                        if isinstance(result, dict) and result.get("requires_manual_run"):
                            message["repair_completed"] = True
            if repair:
                from service.tools.tool_repairs import finish
                finish(repair["id"], completed and not failure["message"] and not asyncio.current_task().cancelling(), repair.get("attempt"))
            chat.save_chat(selected["id"], messages)
            chat.save_failure(selected["id"], failure["message"])
            activity.delete()
            send.enable()
            stop.disable()
            stop.set_visibility(False)
            answer.delete()
            if on_change:
                on_change(selected["id"])
            timeline.refresh()

    async def poll_repairs():
        nonlocal task
        if task and not task.done():
            return
        from service.tools import tool_repairs
        report = tool_repairs.claim(selected["id"])
        if report:
            if not any(m.get("repair_id") == report["id"] for m in messages):
                messages.append({"id": report["id"], "role": "user", "repair_id": report["id"], "content": t("请修复当前工具，完成后由我手动重试。") + "\n\n```json\n" + tool_repairs.summary(report) + "\n```"})
                chat.save_chat(selected["id"], messages)
                timeline.refresh()
            async def repair_turn():
                with feed:
                    await generate_in_slot(repair=report)
            task = asyncio.create_task(repair_turn())

    ui.timer(1.0, poll_repairs)

    def retry():
        nonlocal task
        if task and not task.done():
            return
        if not model_providers.selected():
            connection()
            return
        failure["message"] = ""
        timeline.refresh()
        task = asyncio.create_task(generate())

    def submit():
        nonlocal task
        if task and not task.done():
            return
        if attachments.busy:
            ui.notify(t("文件正在上传，请稍后发送"), type="info")
            return
        text = (composer.value or "").strip()
        if not text:
            from service.files import chat_images, conversation_files
            if not any(chat_images.is_image(item['name']) for item in conversation_files.list_files(selected['id'], pending=True)):
                return
        if not model_providers.selected():
            connection()
            return
        from service.files import chat_images, conversation_files
        image_files = [item for item in conversation_files.list_files(selected['id'], pending=True) if chat_images.is_image(item['name'])]
        if image_files:
            provider, model, connection_data = model_providers.active()
            if not model_providers.supports_images(provider, model, connection_data):
                ui.notify(t('当前模型不支持图片，请选择支持视觉的模型'), type='warning')
                return
        text = text or t('请查看这些图片。')
        message = {"id": uuid4().hex, "role": "user", "content": text, "attachments": attachments.ids()}
        try:
            chat.save_chat(selected["id"], [*messages, message])
        except ValueError as error:
            attachments.notify_error(error)
            return
        messages.append(message)
        failure["message"] = ""
        attachments.render.refresh()
        if on_change:
            on_change(selected["id"])
        composer.set_value("")
        timeline.refresh()
        task = asyncio.create_task(generate())

    with ui.row().classes("calabash-chat w-full h-full min-h-0 gap-0 flex-nowrap") as chat_root:
        with ui.column().classes("chat-main flex-1 min-w-0 h-full gap-0"):
            with ui.row().classes("app-chat-toolbar w-full items-center justify-between px-5 py-2"):
                ui.label(t("AI 对话")).classes("text-xs font-medium text-gray-500")
                with ui.row().classes("items-center gap-1"):
                    preview_toggle, preview_tip = _toolbar_button("preview", t("打开预览"), toggle_preview, leave=True)
            with ui.scroll_area().classes("w-full flex-1 min-h-0"), ui.column().classes("w-full max-w-3xl mx-auto px-6 py-4 gap-0") as feed:
                timeline()
            with ui.column().classes("w-full max-w-3xl mx-auto px-5 pt-2 pb-5 gap-0"):
                with NativeFileDrop().classes("chat-compose w-full gap-1") as compose:
                    attachments.render()
                    composer = ui.textarea(placeholder=t("描述你想创建或修改的工具…")).props("borderless autogrow hide-bottom-space").classes("w-full")
                    composer._props["aria-label"] = t("描述你想创建或修改的工具…")
                    composer.on("compositionstart", js_handler="(e) => { e.target.calabashComposing = true; }")
                    composer.on("compositionend", js_handler="(e) => { e.target.calabashComposing = false; e.target.calabashCompositionEnded = performance.now(); }")
                    composer.on("keydown.enter", submit, js_handler=_COMPOSER_KEYDOWN_JS)
                    with ui.row().classes("w-full items-center justify-between gap-2"):
                        with ui.row().classes("items-center min-w-0 gap-1"):
                            attachments.button()
                            ui.select(model_providers.options(), value=model_providers.selected(), on_change=lambda event: model_providers.select(event.value) if event.value else None).props("borderless dense options-dense hide-bottom-space").classes("chat-model min-w-0 max-w-48").props(f'aria-label="{t("选择模型")}"').tooltip(t("选择模型"))
                        with ui.row().classes("items-center gap-1"):
                            stop, _ = _toolbar_button("stop", t("停止生成"), lambda: task.cancel() if task else None)
                            stop._props["aria-label"] = t("停止生成")
                            stop.disable()
                            stop.set_visibility(False)
                            send, _ = _toolbar_button("send", t("发送"), submit)
                            send.classes("chat-send")
                            send._props["aria-label"] = t("发送")
                    ui.label(t("可选择、拖入或粘贴图片；发送图片会将图片内容提交给所选模型服务")).classes("text-xs text-gray-400 break-words")
                attachments.connect_drop(compose)
        from component.panel_resize import resize_handle

        preview_divider = resize_handle(label="调整预览宽度", minimum=280, maximum=1400, direction=-1)
        preview_divider.classes("chat-preview-divider")
        with ui.column().classes("chat-preview w-1/2 flex-shrink-0 min-w-0 h-full gap-0 border-l border-gray-100 bg-white") as preview_panel:
            with ui.row().classes("app-preview-toolbar w-full items-center justify-between px-3 py-2 gap-2 border-b border-gray-100"):
                back, _ = _toolbar_button("back", t("返回对话"), lambda: set_preview_visible(False))
                back.classes("chat-preview-back")
                ui.label(t("工具预览")).classes("text-xs font-medium text-gray-600")
                with ui.row().classes("items-center gap-1"):
                    save_preview_button, _ = _toolbar_button("save", t("保存到工具列表"), save_preview_tool)
                    refresh_preview_button, _ = _toolbar_button("refresh", t("刷新预览"), lambda: show_preview({"url": preview_state["url"]}), leave=True)
                    open_preview_button, _ = _toolbar_button("open", t("打开完整预览"), lambda: ui.navigate.to(preview_state["url"], new_tab=True) if preview_state["url"] else None)
                    _toolbar_button("close", t("关闭预览"), lambda: set_preview_visible(False), leave=True)
            with ui.column().classes("preview-body w-full flex-1 min-h-0 gap-0"):
                preview_content()
        preview_panel.set_visibility(False)
        preview_divider.props(f"data-panel=c{preview_panel.id}").set_visibility(False)
        restore_preview()
