"""Live, version-bound preview inspection with explicit read and per-action consent."""

import asyncio
import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass, field
from time import monotonic

from service.tools import preview_service

_sessions = {}
MAX_GRANT_SECONDS = 600


def redact(value, secrets=()):
    from service.chat import model_providers
    text = str(value)[:20000]
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            text = text.replace(secret, '[CREDENTIAL REDACTED]')
    for connection in model_providers.load().get('connections', {}).values():
        key = connection.get('key')
        if isinstance(key, str) and key:
            text = text.replace(key, '[CREDENTIAL REDACTED]')
    text = re.sub(r'([?&][A-Za-z0-9_.-]+=)[^\s&#)]+', r'\1[REDACTED]', text)
    return re.sub(r'(?i)(bearer\s+|(?:api[_-]?key|password|secret|token|authorization)\s*[:=]\s*)[^\s,;"}]+', r'\1[CREDENTIAL REDACTED]', text)


@dataclass
class Session:
    run: object
    chat_id: str
    context: str
    client: object
    revision: str
    credentials: tuple = field(default=(), repr=False)
    events: deque = field(default_factory=lambda: deque(maxlen=40))
    approved_at: float = 0
    fingerprint: str = ''
    confirm_action: object = None
    action_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def valid(self):
        from service.files import tool_inputs
        if _sessions.get(self.run.id) is not self:
            raise ValueError('Preview closed; reopen and authorize again')
        owner, chat = tool_inputs.owner(self.context, self.run.preview_key)
        if chat != self.chat_id or owner != f'tool:{self.run.project}/{self.run.name}':
            raise ValueError('Preview ownership changed')
        path = preview_service.get_preview_file(self.run.preview_key)
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != self.revision:
            self.revoke()
            raise ValueError('Source changed; manually refresh preview and authorize again')

    def require(self):
        from service.tools.tool_repairs import model_fingerprint
        self.valid()
        if not self.approved_at or monotonic() - self.approved_at > MAX_GRANT_SECONDS or model_fingerprint() != self.fingerprint:
            self.revoke()
            raise ValueError('Authorize diagnostics on the current preview first')

    def grant(self, callback):
        from service.tools.tool_repairs import model_fingerprint
        self.valid()
        self.fingerprint = model_fingerprint()
        self.approved_at = monotonic()
        self.confirm_action = callback

    def revoke(self):
        self.approved_at = 0
        self.confirm_action = None

    def capture(self, value):
        if not isinstance(value, dict) or len(self.events) >= 40:
            return
        allowed = {'console_error', 'javascript_error', 'unhandled_rejection', 'media_error', 'resource_error', 'request_failed'}
        if value.get('kind') not in allowed:
            return
        # No arbitrary object logging, request bodies, headers or form values.
        clean = {key: redact(value[key], self.credentials)[:1200] for key in ('kind', 'message', 'stack', 'source', 'line', 'code', 'status') if key in value and isinstance(value[key], (str, int))}
        self.events.append(clean)
        self.run.logger.warning('Frontend diagnostic: ' + json.dumps(clean, ensure_ascii=False))

    async def snapshot(self):
        self.require()
        result = await self.client.run_javascript('window.calabashPreviewProbe?.snapshot() || {error: "Preview probe is not ready"}', timeout=8)
        self.require()
        if not isinstance(result, dict):
            raise ValueError('Preview probe returned invalid data')  # noqa: TRY004 - invalid browser response is a protocol error.
        # All browser output is untrusted and bounded. This is a DOM report, not a screenshot.
        raw = json.dumps(result, ensure_ascii=False)
        if len(raw) > 40000:
            raise ValueError('Preview report exceeds limit')
        data = _clean_page(result, self.credentials)
        if data.get('error'):
            raise ValueError('Preview probe is not ready; inspect after loading')
        return {'source': 'preview', 'revision': self.revision, 'log_run_id': self.run.id,
                'untrusted_page': data, 'untrusted_events': list(self.events), 'screenshot': False}


def _clean_page(result, secrets=()):
    data = {}
    for key in ('text', 'error'):
        if isinstance(result.get(key), str):
            data[key] = redact(result[key], secrets)[:1600]
    data['horizontal_overflow'] = result.get('horizontal_overflow') if type(result.get('horizontal_overflow')) is bool else None
    for key, fields in {
        'elements': {'id', 'tag', 'role', 'label', 'enabled', 'input_type', 'editable'},
        'media': {'id', 'paused', 'ended', 'current_time', 'duration', 'ready_state', 'network_state', 'error_code', 'source', 'muted'},
    }.items():
        values = result.get(key, [])
        data[key] = [{k: redact(v, secrets)[:160] if isinstance(v, str) else v for k, v in item.items() if k in fields and isinstance(v, (str, int, float, bool, type(None)))} for item in values[:100] if isinstance(item, dict)] if isinstance(values, list) else []
    return data


def register(run, chat_id, context, client):
    path = preview_service.get_preview_file(run.preview_key)
    session = Session(run, chat_id, context, client, hashlib.sha256(path.read_bytes()).hexdigest())
    from service.tools.tool_repairs import RepairSession
    redactor = RepairSession({})
    redactor.redact(path.read_text(encoding='utf-8'))
    session.credentials = tuple(redactor.secrets.values())
    _sessions[run.id] = session
    client.on_disconnect(session.revoke)
    def close():
        session.revoke()
        _sessions.pop(run.id, None)
    client.on_delete(close)
    return session


def current(chat_id, url):
    from service.tools.preview_publish import resolve
    project, name, key = resolve(chat_id, url)
    sessions = [s for s in _sessions.values() if s.client.has_socket_connection and s.chat_id == chat_id and s.run.preview_key == key and (s.run.project, s.run.name) == (project, name)]
    # Two visible pages may hold different state. Never guess which one to operate.
    if len(sessions) != 1:
        raise ValueError('Open exactly one current preview and authorize diagnostics there')
    sessions[0].valid()
    return sessions[0]


def authorized(chat_id, project, name):
    from service.chat import ai_chat
    url = ai_chat.remembered_preview(chat_id) if chat_id else ''
    if not url:
        raise ValueError('Open and authorize the current preview first')
    session = current(chat_id, url)
    if (session.run.project, session.run.name) != (project, name):
        raise ValueError('Diagnostics are restricted to the authorized preview')
    session.require()
    return session


async def interact(session, **kwargs):
    if session.action_lock.locked():
        return {'dispatched': False, 'status': 'action_confirmation_pending'}
    async with session.action_lock:
        return await _interact(session, **kwargs)


async def _interact(session, *, element_id, action, value='', reason=''):
    session.require()
    if action not in {'click', 'fill'} or not re.fullmatch(r'e[1-9][0-9]{0,6}', element_id or '') or not isinstance(value, str) or len(value) > 1200 or not isinstance(reason, str) or not 1 <= len(reason) <= 500:
        raise ValueError('Invalid bounded preview action')
    snapshot = await session.snapshot()
    candidates = [e for e in snapshot['untrusted_page'].get('elements', []) if e.get('id') == element_id and e.get('enabled')]
    if len(candidates) != 1 or (action == 'fill' and not candidates[0].get('editable')):
        raise ValueError('Inspect again; action target expired or is forbidden')
    request = {'element_id': element_id, 'action': action, 'value': value, 'reason': reason,
               'label': candidates[0].get('label', ''), 'revision': session.revision,
               'tool': f'{session.run.project}/{session.run.name}'}
    callback = session.confirm_action
    if callback is None:
        raise ValueError('Preview action confirmation is unavailable')
    try:
        allowed = await asyncio.wait_for(callback(request), timeout=120)
    except TimeoutError:
        return {'dispatched': False, 'status': 'confirmation_timeout'}
    session.require()
    if not allowed:
        return {'dispatched': False, 'status': 'user_declined'}
    from service.tools.tool_activity import is_tool_running
    if is_tool_running(session.run.project, session.run.name):
        return {'dispatched': False, 'status': 'tool_running'}
    # Revalidate the element after waiting for the user. IDs are bound to actual DOM nodes.
    command = {key: request[key] for key in ('element_id', 'action', 'value')}
    command['expected_label'] = request['label']
    result = await session.client.run_javascript('window.calabashPreviewProbe?.operate(' + json.dumps(command) + ')', timeout=8)
    session.require()
    return {'revision': session.revision, 'log_run_id': session.run.id,
            'untrusted_action_result': result, 'runtime_verified': False,
            'next_action': 'Inspect and check actual postconditions; dispatch is not success.'}


async def verify(session, checks):
    session.require()
    if not isinstance(checks, list) or not 1 <= len(checks) <= 10:
        raise ValueError('Provide 1..10 explicit checks')
    kinds = {'text_visible', 'element_enabled', 'no_horizontal_overflow', 'no_frontend_errors', 'media_time_advances'}
    for check in checks:
        if not isinstance(check, dict) or set(check) - {'kind', 'text', 'element_id'} or check.get('kind') not in kinds:
            raise ValueError('Unsupported acceptance check')
        if check['kind'] == 'text_visible' and (not isinstance(check.get('text'), str) or not 1 <= len(check['text']) <= 200):
            raise ValueError('Text check requires 1..200 characters')
        if check['kind'] in {'element_enabled', 'media_time_advances'} and not re.fullmatch(r'e[1-9][0-9]{0,6}', check.get('element_id', '')):
            raise ValueError('Check requires an element ID from inspection')
    first = await session.snapshot()
    second = first
    if any(check['kind'] == 'media_time_advances' for check in checks):
        await asyncio.sleep(1)
        second = await session.snapshot()
    page = second['untrusted_page']
    results = []
    for check in checks:
        kind = check['kind']
        if kind == 'text_visible':
            passed = check['text'] in page.get('text', '')
        elif kind == 'element_enabled':
            passed = any(e.get('id') == check['element_id'] and e.get('enabled') for e in page.get('elements', []))
        elif kind == 'no_horizontal_overflow':
            passed = page.get('horizontal_overflow') is False
        elif kind == 'no_frontend_errors':
            passed = not session.events
        else:
            before = next((m for m in first['untrusted_page'].get('media', []) if m.get('id') == check['element_id']), {})
            after = next((m for m in page.get('media', []) if m.get('id') == check['element_id']), {})
            passed = bool(before and after and not after.get('paused', True) and not after.get('error_code') and isinstance(before.get('current_time'), (int, float)) and isinstance(after.get('current_time'), (int, float)) and after['current_time'] > before['current_time'] + 0.1)
        results.append({'kind': kind, 'passed': bool(passed)})
    return {'revision': session.revision, 'log_run_id': session.run.id, 'checks': results,
            'status': 'checks_passed' if all(r['passed'] for r in results) else 'checks_failed',
            'scope': 'Only these observed DOM/media checks; no screenshot, audible-output or complete business verification.'}
