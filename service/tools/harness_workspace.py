"""DSH adapter: real drafts, bounded source access and explicit runtime actions."""
import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from core.local_paths import app_dir
from service.chat.source_credentials import SourceCredentials
from service.tools import tool_bundles as bundles
from service.tools import work_drafts
from service.tools.tool_checks import checks
from service.tools.tool_workers import workers

_credentials = {}


def owner(session):
    if not isinstance(session, str) or not 1 <= len(session) <= 200:
        raise ValueError('Invalid session')
    return 'dsh-' + hashlib.sha256(session.encode()).hexdigest()[:40]


def state_path(session):
    root = app_dir() / 'harness' / 'workspaces'
    path = root / (owner(session) + '.json')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Linked workspace state is forbidden')
        if part == app_dir():
            break
    return path


def state(session):
    path = state_path(session)
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    bundles.identity(value['project']); bundles.identity(value['name'])
    return value


def bind(session, project, name):
    bundles.identity(project); bundles.identity(name)
    target = state(session)
    if target and (target['project'], target['name']) != (project, name):
        raise ValueError('This conversation is bound to a different tool. Start a new conversation.')
    path = state_path(session)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name('.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            temporary.chmod(0o600)
            handle.write(json.dumps({'project': project, 'name': name}))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def release(session):
    work_drafts.release(owner(session))
    _credentials.pop(owner(session), None)


def release_all():
    for session_owner in tuple(_credentials):
        work_drafts.release(session_owner)
    _credentials.clear()


def source(session, project, name):
    target = state(session)
    if target and (target['project'], target['name']) != (project, name):
        raise ValueError('This conversation is bound to a different tool')
    return work_drafts.ensure(project, name, owner(session))


async def agent_call(session, call_id, operation, arguments, *, requested_preset=None):
    """Model calls cannot run, publish, delete, install or access arbitrary paths."""
    from service.chat import agent_store
    if not isinstance(arguments, dict):
        raise TypeError('Invalid arguments')
    session_owner = owner(session)
    if not isinstance(call_id, str) or not 1 <= len(call_id) <= 200:
        raise ValueError('Invalid operation identifier')
    from service.tools import ui_presets
    explicit = ui_presets.get(requested_preset)['id'] if requested_preset is not None else None
    style_messages = [{'role': 'user', 'content': '@ui:' + explicit}] if explicit else []
    if operation == 'instructions':
        root = Path(__file__).resolve().parents[2] / 'agent/skills/calabash'
        # Fixed built-in documents only; never interpret a model-supplied path.
        return {'skill': (root / 'SKILL.md').read_text()[:24000], 'target': state(session),
                'protocol': 'Use calabash_tool operations only. Read template for a new tool; read current file before changes. Save drafts, check_tool_build, then tell the user to open preview. Never claim business verification. Never run or publish automatically.'}
    if operation == 'list_tools':
        return bundles.list_tools()
    if operation == 'read_ui_reference':
        reference = arguments.get('reference', 'vue-tool.md')
        if reference not in {'vue-tool.md', 'design.md', 'frontend-debug.md', 'file-workflow.md', 'lifecycle.md', 'quality-gate.md', 'api-contract.md'}:
            raise ValueError('Unknown built-in reference')
        return {'reference': reference, 'content': (Path(__file__).resolve().parents[2] / 'agent/skills/calabash/references' / reference).read_text()[:32000]}
    if operation == 'read_component_api':
        from service.tools.vue_component_api import read_api
        return read_api(arguments.get('component', ''), arguments.get('property_name', ''), offset=arguments.get('offset', 0))
    if operation == 'read_ui_preset':
        target = state(session)
        if explicit:
            return {**ui_presets.reference(explicit), 'selected_by': 'mention'}
        if target:
            existing = source(session, target['project'], target['name'])['files']
            meta = json.loads(existing.get('tool.json', '{}')).get('ui')
            if not meta:
                return {'rules': 'Preserve the existing custom scoped UI; do not replace it with the global default.'}
            try:
                reference = ui_presets.reference(meta['preset'])
            except ValueError:
                reference = {'id': meta['preset'], 'version': meta['version'], 'rules': 'Preserve the existing tool theme snapshot. No installed reference pack.'}
            return {**reference, 'snapshot': True, 'selected_by': 'snapshot',
                    'tokens': _credentials.setdefault(session_owner, SourceCredentials()).redact(existing.get('frontend/calabash-theme.css', ''))}
        return {**ui_presets.reference(ui_presets.default()), 'selected_by': 'default'}
    project, name = (bundles.identity(arguments.get(key)) for key in ('project', 'name'))
    allowed = {'read_tool', 'read_tool_file', 'read_tool_template', 'write_tool_file', 'patch_tool_file',
               'check_tool_build', 'read_build_diagnostics', 'read_api_contract'}
    if operation not in allowed:
        raise ValueError('Unsupported Calabash operation')
    credentials = _credentials.setdefault(session_owner, SourceCredentials())
    if operation == 'read_tool_template':
        from service.tools.tool_templates import base_template
        target = state(session)
        if target and (target['project'], target['name']) != (project, name):
            raise ValueError('Conversation already has a tool')
        return {'files': base_template(project, name), 'executed': False}
    if operation in {'write_tool_file', 'patch_tool_file'}:
        from service.tools import ui_presets
        path = bundles.safe_path(arguments.get('path'))
        try:
            current = source(session, project, name)['files']
        except bundles.ToolUnavailable:
            current = {}
        if path == 'frontend/calabash-theme.css':
            raise ValueError('Theme tokens are host managed')
        if operation == 'patch_tool_file':
            old, new = arguments.get('old'), arguments.get('new')
            if not isinstance(old, str) or not old or not isinstance(new, str):
                raise ValueError('Invalid patch')
            redacted = credentials.redact(current.get(path, ''))
            if redacted.count(old) != 1:
                raise ValueError('Read current file and use one unique literal match')
            content = redacted.replace(old, new, 1)
        else:
            content = arguments.get('content')
        if not isinstance(content, str):
            raise TypeError('Source must be text')
        changes = {path: credentials.restore(content)}
        if explicit and path != 'tool.json' and current.get('tool.json'):
            # An explicit style request owns this metadata change even when the
            # model only edits App.vue. Never rely on the model to update it.
            work_drafts.observe(session_owner, project, name, 'tool.json', current['tool.json'])
            changes['tool.json'] = current['tool.json']
        if 'tool.json' in changes:
            changes = ui_presets.apply(changes, style_messages, current or None)
            if current.get('frontend/calabash-theme.css'):
                work_drafts.observe(session_owner, project, name, 'frontend/calabash-theme.css', current['frontend/calabash-theme.css'])
        bind(session, project, name)
        agent_store.register(session_owner, session_owner)
        digest = hashlib.sha256(json.dumps([operation, arguments, explicit], sort_keys=True).encode()).hexdigest()
        receipt = agent_store.begin(session_owner, call_id, digest)
        if receipt is not None:
            return receipt
        saved = work_drafts.write_files(session_owner, session_owner, project, name, changes)
        result = {'saved': True, 'runtime_verified': False, 'ready_for_check': all(saved['files'].get(p) for p in ('tool.json', 'frontend/App.vue', 'backend/main.py'))}
        agent_store.finish(session_owner, call_id, result)
        return result
    value = source(session, project, name)
    if operation == 'read_tool':
        bind(session, project, name)
        return {'files': [{'path': p, 'lines': len(c.splitlines())} for p, c in value['files'].items()]}
    if operation == 'read_tool_file':
        path = bundles.safe_path(arguments.get('path'))
        raw = value['files'][path]
        offset, limit = arguments.get('offset', 0), arguments.get('limit', 100)
        if type(offset) is not int or type(limit) is not int or not 0 <= offset <= 100000 or not 1 <= limit <= 150:
            raise ValueError('Invalid source page')
        work_drafts.observe(session_owner, project, name, path, raw)
        lines = credentials.redact(raw).splitlines()
        return {'path': path, 'total_lines': len(lines), 'lines': [{'line': i + 1, 'text': line[:1500]} for i, line in enumerate(lines) if offset <= i < offset + limit]}
    if operation == 'check_tool_build':
        entry = checks.ensure(project, name, session_owner, value)
        await asyncio.shield(entry.task)
        return entry.public()
    if operation == 'read_build_diagnostics':
        from service.tools.check_records import read
        return read(project, name, session_owner, value['revision'])
    from service.tools.api_contracts import extract
    return extract(value['files'])


async def preview(session, *, refresh=False):
    target = state(session)
    if not target:
        raise ValueError('No tool draft in this conversation yet')
    project, name = target['project'], target['name']
    value = source(session, project, name)
    async with checks.verified(project, name, owner(session), value):
        if work_drafts.snapshot(project, name)['revision'] != value['revision']:
            raise ValueError('Draft changed during check; retry preview')
        if refresh:
            await workers.close(project, name, owner(session))
        worker = await workers.open(project, name, owner(session))
        if worker.revision != value['revision']:
            await workers.close(project, name, owner(session))
            raise ValueError('Draft changed before preview; retry')
        return {**target, 'url': worker.url, 'revision': worker.revision}


async def publish(session, expected, replace_revision, confirmed):
    if confirmed is not True:
        raise ValueError('User confirmation required')
    target = state(session)
    if not target:
        raise ValueError('No draft')
    project, name = target['project'], target['name']
    value = source(session, project, name)
    if value['revision'] != expected:
        raise ValueError('Preview changed; refresh before saving')
    async with checks.verified(project, name, owner(session), value) as built, workers.publication(project, name):
        if work_drafts.snapshot(project, name)['revision'] != expected:
            raise ValueError('Draft changed while saving')
        bundles.write(project, name, value['files'], replace_revision, built_dist=built / 'dist')
    from service.tools.harness_library import conversation
    conversation(project, name, session)
    return {'saved': True}
