"""UI-independent chat generation, replayable events and per-chat cancellation."""

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from uuid import uuid4

from service.chat import ai_chat


@dataclass
class ChatRun:
    chat_id: str
    id: str = field(default_factory=lambda: uuid4().hex)
    status: str = 'running'
    sequence: int = 0
    events: deque = field(default_factory=lambda: deque(maxlen=1000))
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None

    def emit(self, kind, value):
        if kind == 'activity' and self.events and self.events[-1]['kind'] == kind and self.events[-1]['value'] == value:
            return
        self.sequence += 1
        self.events.append({'id': self.sequence, 'kind': kind, 'value': value})
        self.changed.set()

    def snapshot(self):
        return {'id': self.id, 'chat_id': self.chat_id, 'status': self.status,
                'sequence': self.sequence, 'events': list(self.events)}


class ChatRuns:
    def __init__(self):
        self.runs = {}

    def get(self, chat_id):
        return self.runs.get(chat_id)

    def start(self, chat_id, text, attachments=()):
        if not ai_chat.chat_exists(chat_id):
            raise ValueError('Conversation unavailable')
        previous = self.get(chat_id)
        if previous and previous.status == 'running':
            raise ValueError('Conversation is already running')
        if not isinstance(text, str) or not text.strip() or len(text) > 20000:
            raise ValueError('Invalid message')
        from service.chat import model_providers
        from service.files import chat_images
        from service.files import conversation_files as files
        pending = {item['id'] for item in files.list_files(chat_id, pending=True)}
        if len(attachments) > files.MAX_FILES or not set(attachments) <= pending:
            raise ValueError('Invalid attachments')
        if any(files.check(chat_id, value) != 'ready' for value in attachments):
            raise ValueError('Attachment changed')
        images = [value for value in attachments if chat_images.is_image(files.get_record(chat_id, value)['name'])]
        if images:
            provider, model, connection = model_providers.active()
            if not model_providers.supports_images(provider, model, connection):
                raise ValueError('Selected model does not support images')
        messages = ai_chat.read_chat(chat_id)
        messages.append({'role': 'user', 'content': text.strip(), 'id': uuid4().hex,
                         'attachments': list(attachments)})
        ai_chat.save_chat(chat_id, messages)
        run = ChatRun(chat_id)
        self.runs[chat_id] = run
        run.task = asyncio.create_task(self._generate(run, messages))
        return run

    async def _generate(self, run, messages):
        try:
            ai_chat.save_failure(run.chat_id, '')
            async for kind, value in ai_chat.respond(messages, run.chat_id):
                run.emit(kind, value)
                if kind in {'preview', 'manual_preview'} and isinstance(value, dict):
                    url = value.get('preview_url') or value.get('url')
                    if url:
                        ai_chat.remember_preview(run.chat_id, url)
            run.status = 'completed'
        except asyncio.CancelledError:
            run.status = 'cancelled'
        except Exception as failure:  # noqa: BLE001 - provider failures must not expose credentials to the UI.
            from core.logger import get_logger
            get_logger(__name__).exception('Chat generation failed')
            # Do not send raw provider errors, request bodies or credentials.
            from core.i18n import t
            error = t('本次生成未完成，进度已保留；可以继续生成，或补充要求后再试')
            from service.chat.agent_model import PublicAgentError
            if isinstance(failure, PublicAgentError) or str(failure) == t('请在设置中配置模型连接'):
                error = str(failure)
            ai_chat.save_failure(run.chat_id, error)
            run.emit('error', error)
            run.status = 'failed'
        finally:
            run.emit('status', run.status)
            from service.tools.bundle_debug import release_logs
            release_logs(run.chat_id)

    def cancel(self, chat_id):
        run = self.get(chat_id)
        if run and run.status == 'running' and run.task:
            run.task.cancel()

    def resume(self, chat_id):
        previous = self.get(chat_id)
        if previous and previous.status == 'running':
            raise ValueError('Conversation is already running')
        messages = ai_chat.read_chat(chat_id)
        user = next((item for item in reversed(messages) if item.get('role') == 'user'), None)
        if not user or user.get('agent_completed'):
            raise ValueError('No pending generation to resume')
        run = ChatRun(chat_id)
        self.runs[chat_id] = run
        run.task = asyncio.create_task(self._generate(run, messages))
        return run

    async def close(self):
        tasks = [run.task for run in self.runs.values() if run.task and not run.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def stream(self, run, after=0):
        while True:
            run.changed.clear()
            if run.events and after < run.events[0]['id'] - 1:
                after = run.sequence
                yield 'event: snapshot\ndata: ' + json.dumps(run.snapshot(), ensure_ascii=False) + '\n\n'
            for event in tuple(run.events):
                if event['id'] > after:
                    after = event['id']
                    yield f'id: {after}\ndata: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
            if run.status != 'running':
                return
            try:
                await asyncio.wait_for(run.changed.wait(), timeout=15)
            except TimeoutError:
                yield ': heartbeat\n\n'


runs = ChatRuns()
