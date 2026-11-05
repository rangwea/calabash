"""Loopback workspace API. UI uses services, never direct database writes."""

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from core.app_info import APP_NAME, APP_VERSION
from core.i18n import _english, language, set_language
from service.chat import ai_chat, model_providers
from service.chat.chat_runs import runs
from service.files import conversation_files

router = APIRouter(prefix='/api/workspace')


def live(chat_id):
    if not ai_chat.chat_exists(chat_id):
        raise HTTPException(404, 'Conversation unavailable')


@router.get('/bootstrap')
def bootstrap():
    from service.tools import ui_presets
    return {'name': APP_NAME, 'version': APP_VERSION, 'language': language(),
            'translations': _english(), 'models': model_providers.options(),
            'selected_model': model_providers.selected(), 'ui_presets': ui_presets.catalog(), 'default_ui': ui_presets.default()}


@router.get('/chats')
def chats():
    return [{'id': identity, 'title': title,
             'running': bool(runs.get(identity) and runs.get(identity).status == 'running')}
            for identity, title in ai_chat.conversations()]


@router.post('/chats', status_code=201)
def create_chat():
    identity = uuid4().hex
    ai_chat.save_chat(identity, [])
    return {'id': identity}


@router.get('/chats/{chat_id}')
def chat(chat_id: str):
    live(chat_id)
    run = runs.get(chat_id)
    return {'id': chat_id, 'messages': ai_chat.read_chat(chat_id),
            'failure': ai_chat.read_failure(chat_id), 'preview': ai_chat.remembered_preview(chat_id),
            'run': run.snapshot() if run else None,
            'attachments': conversation_files.list_files(chat_id, pending=True),
            'files': conversation_files.list_files(chat_id)}


@router.get('/chats/{chat_id}/images/{file_id}')
def thumbnail(chat_id: str, file_id: str):
    live(chat_id)
    import base64

    from service.files.chat_images import encode
    encoded = encode(chat_id, file_id, thumbnail=True)
    kind, content = encoded.split(',', 1)
    return Response(base64.b64decode(content), media_type=kind.removeprefix('data:').removesuffix(';base64'))


class ChatEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    pinned: bool | None = None


@router.patch('/chats/{chat_id}')
def edit_chat(chat_id: str, body: ChatEdit):
    live(chat_id)
    if body.title is not None:
        ai_chat.rename_chat(chat_id, body.title)
    if body.pinned is not None:
        ai_chat.pin_chat(chat_id, body.pinned)
    return {'ok': True}


@router.delete('/chats/{chat_id}')
def delete_chat(chat_id: str):
    live(chat_id)
    if runs.get(chat_id) and runs.get(chat_id).status == 'running':
        raise HTTPException(409, 'Stop generation before deleting')
    ai_chat.delete_chat(chat_id)
    runs.runs.pop(chat_id, None)
    from service.tools.bundle_debug import grants, release_logs
    grants.pop(chat_id, None)
    release_logs(chat_id)
    return {'ok': True}


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    attachments: list[str] = Field(default_factory=list, max_length=20)


@router.post('/chats/{chat_id}/runs', status_code=202)
async def start_run(chat_id: str, body: Message):
    live(chat_id)
    try:
        return runs.start(chat_id, body.text, body.attachments).snapshot()
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@router.post('/chats/{chat_id}/cancel')
async def cancel(chat_id: str):
    live(chat_id)
    runs.cancel(chat_id)
    return {'ok': True}


@router.post('/chats/{chat_id}/resume', status_code=202)
async def resume(chat_id: str):
    live(chat_id)
    return runs.resume(chat_id).snapshot()


@router.get('/chats/{chat_id}/events')
async def events(chat_id: str, request: Request, after: int = 0):
    live(chat_id)
    run = runs.get(chat_id)
    if run is None:
        raise HTTPException(404, 'Run unavailable')
    try:
        cursor = max(after, int(request.headers.get('last-event-id', '0')))
    except ValueError:
        raise HTTPException(400, 'Invalid cursor') from None
    return StreamingResponse(runs.stream(run, cursor), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


@router.post('/chats/{chat_id}/attachments')
async def upload(chat_id: str, file: UploadFile):
    live(chat_id)
    class Upload:
        name = file.filename or 'file'

        def size(self):
            return file.size or 0

        async def iterate(self):
            while chunk := await file.read(64 * 1024):
                yield chunk
    try:
        return await conversation_files.store_upload(chat_id, Upload())
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@router.delete('/chats/{chat_id}/attachments/{file_id}')
def remove_attachment(chat_id: str, file_id: str):
    live(chat_id)
    return {'ok': conversation_files.remove_pending(chat_id, file_id)}


class Selection(BaseModel):
    ticket: str = Field(pattern=r'^[a-f0-9]{32}$')


@router.post('/chats/{chat_id}/selections')
def native_selection(chat_id: str, body: Selection):
    live(chat_id)
    return conversation_files.consume_selection(chat_id, body.ticket)


@router.get('/settings/models')
def models():
    # Never return saved credentials to the browser.
    data = model_providers.load()
    return {'selected': model_providers.selected(), 'connections': {
        key: {k: v for k, v in value.items() if k != 'key'} | {'configured': bool(value.get('key'))}
        for key, value in data['connections'].items()}}


class ModelConnection(BaseModel):
    provider: str
    base_url: str = Field(max_length=2000)
    key: str = Field(default='', max_length=2000)
    models: list[str] = Field(default_factory=list, max_length=50)
    vision_models: list[str] = Field(default_factory=list, max_length=50)


@router.put('/settings/models')
def save_model(body: ModelConnection):
    from urllib.parse import urlsplit
    parts = urlsplit(body.base_url)
    if body.provider not in model_providers.PROVIDERS or parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise HTTPException(400, 'Valid HTTPS model endpoint required')
    data = model_providers.load()
    prior = data['connections'].get(body.provider, {})
    data['connections'][body.provider] = {'key': body.key or prior.get('key', ''),
        'base_url': body.base_url.rstrip('/'), 'models': body.models, 'vision_models': body.vision_models}
    if not data['selected'] and body.models:
        data['selected'] = f'{body.provider}::{body.models[0]}'
    model_providers.save(data)
    return {'ok': True}


@router.post('/settings/models/discover')
async def discover_models(body: ModelConnection):
    prior = model_providers.load()['connections'].get(body.provider, {})
    return await model_providers.available_models(body.provider, {'key': body.key or prior.get('key', ''), 'base_url': body.base_url})


@router.get('/settings/capabilities')
async def capabilities():
    import asyncio

    from service.capabilities.capability_packs import official_manager
    manager = official_manager()
    return {'configured': manager.configured, 'packs': [await asyncio.to_thread(manager.status, identity) for identity in ('media.ffmpeg', 'document.ocr')]}


@router.post('/settings/capabilities/import')
async def import_capability(file: UploadFile, confirmed: bool = False):
    if not confirmed:
        raise HTTPException(409, 'Import confirmation required')
    import asyncio

    from core.local_paths import app_dir
    from service.capabilities.capability_manifest import MAX_ARCHIVE, PackError
    from service.capabilities.capability_packs import official_manager
    directory = app_dir() / 'imports'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (uuid4().hex + '.zip')
    total = 0
    try:
        with path.open('xb') as output:
            path.chmod(0o600)
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ARCHIVE:
                    raise HTTPException(413, 'Plugin archive too large')
                output.write(chunk)
        return await asyncio.to_thread(official_manager().import_zip, path)
    except PackError as error:
        raise HTTPException(400, error.code) from None
    finally:
        path.unlink(missing_ok=True)


class Preferences(BaseModel):
    default_ui: str | None = None
    language: str | None = None
    model: str | None = None


@router.patch('/settings')
def preferences(body: Preferences):
    if body.default_ui is not None:
        from service.tools.ui_presets import set_default
        set_default(body.default_ui)
    if body.language is not None:
        set_language(body.language)
    if body.model is not None:
        model_providers.select(body.model)
    return {'ok': True}


class DiagnosticGrant(BaseModel):
    project: str
    name: str
    confirmed: bool = False


@router.post('/chats/{chat_id}/diagnostics')
async def authorize_diagnostics(chat_id: str, body: DiagnosticGrant):
    live(chat_id)
    if not body.confirmed:
        raise HTTPException(409, 'Diagnostic confirmation required')
    from service.tools.bundle_debug import grant
    await grant(chat_id, body.project, body.name)
    return {'ok': True}


@router.delete('/chats/{chat_id}/diagnostics')
def revoke_diagnostics(chat_id: str):
    from service.tools.bundle_debug import grants
    grants.pop(chat_id, None)
    return {'ok': True}


@router.get('/chats/{chat_id}/diagnostics/requests')
def diagnostic_requests(chat_id: str):
    live(chat_id)
    from service.tools.bundle_debug import requests
    return requests(chat_id)


class ConfirmAction(BaseModel):
    approved: bool


@router.post('/chats/{chat_id}/diagnostics/requests/{identity}')
def confirm_action(chat_id: str, identity: str, body: ConfirmAction):
    live(chat_id)
    from service.tools.bundle_debug import confirm
    confirm(chat_id, identity, body.approved)
    return {'ok': True}


class Repair(DiagnosticGrant):
    published: bool = False


@router.post('/chats/{chat_id}/repair', status_code=202)
async def repair(chat_id: str, body: Repair):
    live(chat_id)
    if not body.confirmed:
        raise HTTPException(409, 'Repair confirmation required')
    from service.tools.bundle_debug import approve_logs
    if body.published:
        from service.tools import tool_bundles
        path = tool_bundles.directory(body.project, body.name, chat_id)
        if path.exists() and tool_bundles.read(body.project, body.name, chat_id)['revision'] != tool_bundles.read(body.project, body.name)['revision']:
            raise HTTPException(409, 'This conversation has unsaved preview changes. Repair that preview or save it first.')
    approve_logs(chat_id, body.project, body.name, published=body.published)
    from core.i18n import t
    text = t('请修复工具 {project}/{name}，保留现有界面和功能。完成后我会手动试用和保存。', project=body.project, name=body.name)
    try:
        return runs.start(chat_id, text).snapshot()
    except ValueError:
        from service.tools.bundle_debug import release_logs
        release_logs(chat_id)
        raise
