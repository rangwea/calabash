"""Consent-gated diagnostics on current Vue preview, scoped to model and revision."""

import asyncio
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

from service.chat import ai_chat, model_providers
from service.tools import tool_bundles as bundles
from service.tools.tool_workers import workers

grants = {}
pending = {}
repair_grants = {}


def approve_logs(chat_id, project, name, *, published=False):
    worker = workers.current(project, name, None if published else chat_id)
    if not worker or not worker.log_run:
        raise ValueError('No current tool run to diagnose')
    source = bundles.read(project, name, None if published else chat_id)
    if source['revision'] != worker.revision:
        raise ValueError('Code changed; retry manually before confirming repair')
    release_logs(chat_id)
    worker.log_run.retain()
    paths = [worker.log_run.path.with_name('tool.1.log'), worker.log_run.path]
    signatures = {str(path): (path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths if path.is_file() and not path.is_symlink()}
    repair_grants[chat_id] = {'worker': worker, 'revision': source['revision'], 'fingerprint': fingerprint(), 'time': time.monotonic(), 'published': published, 'signatures': signatures}
    return worker.log_run.id


def release_logs(chat_id):
    grant = repair_grants.pop(chat_id, None)
    if grant:
        grant['worker'].log_run.close()


def read_logs(chat_id, project, name, *, offset=0, limit=60, query='', model_identity=None):
    grant = repair_grants.get(chat_id)
    if not grant or grant['fingerprint'] != fingerprint() or model_identity and grant['fingerprint'] != model_identity or time.monotonic() - grant['time'] > 600:
        raise ValueError('User-confirmed log access required')
    worker = grant['worker']
    if (worker.project, worker.name) != (project, name) or bundles.read(project, name, None if grant['published'] else chat_id)['revision'] != grant['revision']:
        raise ValueError('Code changed; retry and confirm again')
    if not 0 <= offset <= 100000 or not 1 <= limit <= 100 or len(query) > 200:
        raise ValueError('Invalid log page')
    from service.chat.source_credentials import SourceCredentials
    from service.tools.browser_diagnostics import redact
    credentials = SourceCredentials()
    for content in bundles.read(project, name, None if grant['published'] else chat_id)['files'].values():
        credentials.redact(content)
    secrets = tuple(credentials.values.values())
    paths = [worker.log_run.path.with_name('tool.1.log'), worker.log_run.path]
    lines = []
    if any(not Path(path).is_file() for path in grant['signatures']):
        raise ValueError('Log window unavailable; retry and confirm again')
    for path in paths:
        if path.is_file() and not path.is_symlink():
            info = path.stat()
            signature = (info.st_ino, info.st_size, info.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
            if grant['signatures'].get(str(path)) != signature:
                raise ValueError('Log changed; retry and confirm current failure again')
            for line in path.read_text(errors='replace').splitlines():
                if not query or query in line:
                    lines.append(redact(line, secrets)[:2000])
    return {'run_id': worker.log_run.id, 'revision': grant['revision'], 'offset': offset,
            'untrusted_lines': lines[offset:offset + limit], 'more': len(lines) > offset + limit}


def fingerprint():
    return hashlib.sha256(json.dumps(model_providers.active(), sort_keys=True).encode()).hexdigest()


def target(chat_id, project, name):
    worker = workers.items.get(workers.key(project, name, chat_id))
    if not ai_chat.chat_exists(chat_id) or not worker or worker.process.poll() is not None:
        raise ValueError('Open the current preview first')
    if bundles.read(project, name, chat_id)['revision'] != worker.revision:
        raise ValueError('Source changed; manually refresh and authorize again')
    return worker


async def request(worker, operation, payload=None):
    async with httpx.AsyncClient(trust_env=False, timeout=12) as client:
        response = await client.post(f'http://127.0.0.1:{worker.port}/api/sdk/debug/request',
            headers={'Authorization': 'Bearer ' + worker.token, 'X-Calabash-Host': worker.host_token}, json={'operation': operation, 'request': payload})
        response.raise_for_status()
        return response.json()


async def grant(chat_id, project, name):
    worker = target(chat_id, project, name)
    page = await request(worker, 'snapshot')
    if not page.get('page') or page.get('error'):
        raise ValueError('Preview not ready')
    grants[chat_id] = {'worker': worker, 'page': page['page'], 'fingerprint': fingerprint(), 'time': time.monotonic()}


def require(chat_id, project, name, model_identity=None):
    worker = target(chat_id, project, name)
    value = grants.get(chat_id)
    if not value or value['worker'] is not worker or time.monotonic() - value['time'] > 600 or value['fingerprint'] != fingerprint() or model_identity and value['fingerprint'] != model_identity:
        raise ValueError('Authorize current preview diagnostics first')
    return worker, value


async def inspect(chat_id, project, name, model_identity=None):
    worker, value = require(chat_id, project, name, model_identity)
    page = await request(worker, 'snapshot')
    if page.get('page') != value['page'] or page.get('error'):
        grants.pop(chat_id, None)
        raise ValueError('Page refreshed; authorize again')
    require(chat_id, project, name, model_identity)
    from service.chat.source_credentials import SourceCredentials
    from service.tools.browser_diagnostics import clean_page, redact
    credentials = SourceCredentials()
    for content in bundles.read(project, name, chat_id)['files'].values():
        credentials.redact(content)
    secrets = tuple(credentials.values.values())
    clean = clean_page(page, secrets)
    events = [{'kind': str(event.get('kind', ''))[:40], 'message': redact(event.get('message', ''), secrets)[:1200], 'stack': redact(event.get('stack', ''), secrets)[:2000]}
              for event in page.get('events', [])[:40] if isinstance(event, dict)]
    return {'revision': worker.revision, 'untrusted_page': clean, 'untrusted_events': events, 'scope': 'Observed DOM/media only, not visual or full business verification'}


async def interact(chat_id, project, name, element_id, action, reason, value='', model_identity=None):
    if action not in {'click', 'fill'} or not reason or len(reason) > 500 or len(value) > 1200:
        raise ValueError('Invalid preview action')
    if any(item['chat_id'] == chat_id for item in pending.values()):
        raise ValueError('A preview action is already awaiting confirmation')
    page = await inspect(chat_id, project, name, model_identity)
    element = next((item for item in page['untrusted_page']['elements'] if item['id'] == element_id), None)
    if not element or not element.get('enabled'):
        raise ValueError('Control unavailable')
    identity = uuid4().hex
    future = asyncio.get_running_loop().create_future()
    pending[identity] = {'id': identity, 'chat_id': chat_id, 'project': project, 'name': name,
                         'revision': page['revision'], 'action': action, 'label': element['label'],
                         'value': value, 'reason': reason, 'future': future}
    try:
        accepted = await asyncio.wait_for(future, 120)
        if not accepted:
            return {'status': 'user_declined', 'dispatched': False}
        await inspect(chat_id, project, name, model_identity)
        worker, _ = require(chat_id, project, name, model_identity)
        if (await workers.status(worker)).get('running'):
            raise ValueError('Tool is running')
        result = await request(worker, 'operate', {'element_id': element_id, 'action': action, 'value': value, 'expected_label': element['label']})
        return {**result, 'runtime_verified': False}
    finally:
        pending.pop(identity, None)


def requests(chat_id):
    return [{key: value for key, value in item.items() if key != 'future'} for item in pending.values() if item['chat_id'] == chat_id]


def confirm(chat_id, identity, approved):
    item = pending.get(identity)
    if not item or item['chat_id'] != chat_id or item['future'].done():
        raise ValueError('Action expired')
    item['future'].set_result(approved)
