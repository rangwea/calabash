"""Host-owned tool lifecycle endpoints for Vue/Python directory tools."""

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from service.chat import ai_chat
from service.tools import tool_bundles as bundles
from service.tools.tool_checks import checks
from service.tools.tool_workers import build_bundle, workers

router = APIRouter(prefix='/api/workspace/tools')


class Target(BaseModel):
    project: str
    name: str


class PreviewContext(BaseModel):
    chat_id: str


@router.post('/{project}/{name}/preview/detach')
async def detach_preview(project: str, name: str, body: PreviewContext):
    if not ai_chat.chat_exists(body.chat_id):
        raise HTTPException(404, 'Conversation unavailable')
    await workers.detach(project, name, body.chat_id)
    return {'ok': True}


@router.post('/{project}/{name}/preview/open')
async def preview_open(project: str, name: str, body: PreviewContext):
    if not ai_chat.chat_exists(body.chat_id):
        raise HTTPException(404, 'Conversation unavailable')
    source = bundles.read(project, name, body.chat_id)
    checks.ensure(project, name, body.chat_id, source)
    worker = workers.items.get(workers.key(project, name, body.chat_id))
    if worker and worker.revision != source['revision']:
        await workers.close(project, name, body.chat_id)
    worker = await workers.open(project, name, body.chat_id)
    return {'url': worker.url, 'revision': worker.revision}


class CheckRequest(PreviewContext):
    retry: bool = False


@router.post('/{project}/{name}/preview/check')
async def check_preview(project: str, name: str, body: CheckRequest):
    if not ai_chat.chat_exists(body.chat_id):
        raise HTTPException(404, 'Conversation unavailable')
    source = bundles.read(project, name, body.chat_id)
    state = checks.ensure(project, name, body.chat_id, source, retry=body.retry).public()
    return {key: state[key] for key in ('revision', 'state')}


class NativeSelection(BaseModel):
    ticket: str
    chat_id: str | None = None


@router.post('/{project}/{name}/inputs/selection')
async def selected_inputs(project: str, name: str, body: NativeSelection):
    import httpx

    from service.files.conversation_files import consume_selection_paths
    worker = workers.items.get(workers.key(project, name, body.chat_id))
    if not worker or worker.process.poll() is not None:
        raise HTTPException(404, 'Tool is not open')
    paths = consume_selection_paths(body.ticket)
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.post(f'http://127.0.0.1:{worker.port}/api/sdk/native-inputs',
            headers={'Authorization': 'Bearer ' + worker.token, 'X-Calabash-Host': worker.host_token}, json={'paths': paths})
        if response.status_code != 200:
            raise HTTPException(409, 'Unable to append selected tool inputs')
        return response.json()


class ResultAction(BaseModel):
    action: str


@router.post('/{project}/{name}/results/{file_id}/action')
async def result_action(project: str, name: str, file_id: str, body: ResultAction):
    import asyncio
    bundles.identity(project); bundles.identity(name)
    from service.files.tool_outputs import ToolOutputs
    outputs = ToolOutputs(owner=(f'tool:{project}/{name}', None))
    if body.action == 'save':
        return {'ticket': outputs.save_ticket(file_id)}
    if body.action not in {'open', 'reveal'}:
        raise HTTPException(400, 'Unknown result action')
    await asyncio.to_thread(outputs.open, file_id, reveal=body.action == 'reveal')
    return {'ok': True}


@router.get('')
def list_tools():
    return bundles.list_tools()


@router.post('/open')
async def open_tool(body: Target):
    worker = await workers.open(body.project, body.name)
    return {'url': worker.url, 'revision': worker.revision}


@router.get('/{project}/{name}/runtime')
async def runtime_status(project: str, name: str, chat_id: str | None = None):
    if chat_id is not None and not ai_chat.chat_exists(chat_id):
        raise HTTPException(404, 'Conversation unavailable')
    from service.tools.tool_health import snapshot
    return await snapshot(project, name, chat_id)


@router.get('/{project}/{name}/status')
async def status(project: str, name: str):
    worker = workers.items.get(workers.key(project, name))
    return await workers.status(worker) if worker and worker.process.poll() is None else {'running': False}


@router.post('/{project}/{name}/close')
async def close(project: str, name: str):
    await workers.close(project, name)
    return {'ok': True}


@router.post('/{project}/{name}/chat')
def tool_chat(project: str, name: str):
    source = bundles.read(project, name)
    meta = bundles.validate(source['files'])
    return {'id': ai_chat.get_or_create_tool_chat(project, name, meta.get('title', name))}


@router.get('/{project}/{name}/export')
def export(project: str, name: str):
    return Response(bundles.export_zip(project, name), media_type='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="{bundles.identity(name)}.zip"'})


@router.post('/{project}/{name}/export-ticket')
def export_ticket(project: str, name: str):
    from service.files.tool_outputs import ToolOutputs
    outputs = ToolOutputs(owner=(f'export:{project}/{name}', None))
    content = bundles.export_zip(project, name)
    identity = outputs.write(name + '.zip', lambda destination: destination.write_bytes(content))
    return {'ticket': outputs.save_ticket(identity)}


class ImportBundle(BaseModel):
    files: dict[str, str]
    revision: str = ''
    confirmed: bool = False


@router.post('/inspect')
async def inspect(file: UploadFile):
    data = await file.read(bundles.MAX_TOTAL + 1)
    files = bundles.inspect_zip(data)
    meta = bundles.validate(files)
    return {'manifest': meta, 'files': files}


@router.post('/import')
async def import_bundle(body: ImportBundle):
    if not body.confirmed:
        raise HTTPException(409, 'Import confirmation required')
    meta = bundles.validate(body.files)
    if await workers.running(meta['project'], meta['name']):
        raise HTTPException(409, 'Stop the running tool before replacing it')
    built = await build_bundle(body.files)
    async with workers.publication(meta['project'], meta['name']):
        return bundles.write(meta['project'], meta['name'], body.files, body.revision, built_dist=built / 'dist')


class Publish(BaseModel):
    chat_id: str
    revision: str
    replace_revision: str = ''
    confirmed: bool = False


@router.post('/{project}/{name}/publish')
async def publish(project: str, name: str, body: Publish):
    if not body.confirmed or not ai_chat.chat_exists(body.chat_id):
        raise HTTPException(409, 'Publish confirmation required')
    if await workers.running(project, name):
        raise HTTPException(409, 'Stop the running tool before replacing it')
    source = bundles.read(project, name, body.chat_id)
    if source['source'] != 'preview' or source['revision'] != body.revision:
        raise HTTPException(409, 'Preview changed; inspect latest revision')
    async with checks.verified(project, name, body.chat_id, source) as built:
        if bundles.read(project, name, body.chat_id)['revision'] != source['revision']:
            raise HTTPException(409, 'Preview changed during build')
        async with workers.publication(project, name):
            if bundles.read(project, name, body.chat_id)['revision'] != source['revision']:
                raise HTTPException(409, 'Preview changed during publication')
            result = bundles.write(project, name, source['files'], body.replace_revision, built_dist=built / 'dist')
    ai_chat.bind_tool_chat(project, name, body.chat_id, bundles.validate(source['files']).get('title', name))
    return result


@router.post('/{project}/{name}/refresh')
async def refresh(project: str, name: str):
    await workers.close(project, name)
    worker = await workers.open(project, name)
    return {'url': worker.url, 'revision': worker.revision}


@router.get('/{project}/{name}/source')
def source(project: str, name: str, chat_id: str | None = None):
    if chat_id and not ai_chat.chat_exists(chat_id):
        raise HTTPException(404, 'Conversation unavailable')
    return bundles.read(project, name, chat_id)


class Delete(BaseModel):
    revision: str
    confirmed: bool = False


@router.delete('/{project}/{name}')
def delete(project: str, name: str, body: Delete):
    if not body.confirmed:
        raise HTTPException(409, 'Delete confirmation required')
    bundles.delete(project, name, body.revision)
    return {'ok': True}
