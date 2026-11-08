"""Host-only tool library actions. ZIP transfers are bounded, inert and ephemeral."""
import base64
import json
import time
from uuid import uuid4

from core.local_paths import app_dir
from service.tools import harness_workspace as workspace
from service.tools import tool_bundles as bundles
from service.tools.tool_workers import build_bundle, workers

CHUNK = 192 * 1024
_tickets = {}


def _prune():
    for key, value in tuple(_tickets.items()):
        if value['expires'] < time.monotonic():
            del _tickets[key]


def _ticket(kind, **values):
    _prune()
    if len(_tickets) >= 4:
        raise ValueError('Too many pending archives')
    key = uuid4().hex
    _tickets[key] = {'kind': kind, 'expires': time.monotonic() + 600, **values}
    return key


def _get(key, kind):
    _prune()
    value = _tickets.get(key)
    if not value or value['kind'] != kind:
        raise ValueError('Archive selection expired')
    return value


def conversation(project, name, session=None):
    project, name = bundles.identity(project), bundles.identity(name)
    bundles.read(project, name)
    root = app_dir() / 'harness' / 'tool-conversations'
    path = root / f'{project}.{name}.json'
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Linked conversation mapping is forbidden')
        if part == app_dir():
            break
    if session is None:
        if not path.exists():
            return None
        if path.stat().st_size > 2048:
            raise ValueError('Invalid conversation mapping')
        result = json.loads(path.read_text())
        workspace.owner(result)
        return result
    workspace.owner(session)
    workspace.bind(session, project, name)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = root / (uuid4().hex + '.tmp')
    try:
        with temporary.open('x') as handle:
            temporary.chmod(0o600)
            json.dump(session, handle)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return session


async def dispatch(operation, params):
    if workers.stopping:
        raise ValueError('Calabash is closing')
    if operation == 'conversation' and set(params) == {'project', 'name', 'session'}:
        return conversation(**params)
    if operation == 'delete' and set(params) == {'project', 'name', 'revision', 'confirmed'}:
        if params['confirmed'] is not True:
            raise ValueError('Deletion confirmation required')
        bundles.delete(params['project'], params['name'], params['revision'])
        return {'deleted': True}
    if operation == 'begin' and not params:
        return {'ticket': _ticket('upload', data=bytearray())}
    if operation == 'upload' and set(params) == {'ticket', 'offset', 'data'}:
        value = _get(params['ticket'], 'upload')
        if type(params['offset']) is not int or params['offset'] != len(value['data']):
            raise ValueError('Unexpected archive offset')
        if not isinstance(params['data'], str) or len(params['data']) > CHUNK * 4 // 3:
            raise ValueError('Archive chunk too large')
        chunk = base64.b64decode(params['data'], validate=True)
        if len(value['data']) + len(chunk) > bundles.MAX_TOTAL:
            raise ValueError('Archive too large')
        value['data'].extend(chunk)
        return {'offset': len(value['data'])}
    if operation == 'inspect' and set(params) == {'ticket'}:
        value = _get(params['ticket'], 'upload')
        files = bundles.inspect_zip(bytes(value['data']))
        meta = bundles.validate(files)
        existing = next((tool for tool in bundles.list_tools() if (tool['project'], tool['name']) == (meta['project'], meta['name'])), None)
        value.update(kind='import', files=files)
        del value['data']
        return {'manifest': {key: meta.get(key, '') for key in ('project', 'name', 'title', 'description')}, 'revision': existing['revision'] if existing else ''}
    if operation == 'import' and set(params) == {'ticket', 'revision', 'confirmed'}:
        if params['confirmed'] is not True:
            raise ValueError('Import confirmation required')
        value = _get(params['ticket'], 'import')
        files = value['files']
        meta = bundles.validate(files)
        project, name = meta['project'], meta['name']
        if workers.is_open(project, name) or await workers.running(project, name):
            raise ValueError('Close this tool before replacing it')
        built = await build_bundle(files)
        async with workers.publication(project, name):
            if workers.is_open(project, name):
                raise ValueError('Close this tool before replacing it')
            result = bundles.write(project, name, files, params['revision'], built_dist=built / 'dist')
        _tickets.pop(params['ticket'], None)
        return result
    if operation == 'export' and set(params) == {'project', 'name'}:
        data = bundles.export_zip(params['project'], params['name'])
        return {'ticket': _ticket('export', data=data), 'size': len(data), 'name': bundles.identity(params['name']) + '.zip'}
    if operation == 'read' and set(params) == {'ticket', 'offset'}:
        value = _get(params['ticket'], 'export')
        offset = params['offset']
        if type(offset) is not int or not 0 <= offset < len(value['data']):
            raise ValueError('Invalid archive offset')
        return {'data': base64.b64encode(value['data'][offset:offset + CHUNK]).decode('ascii')}
    if operation == 'discard' and set(params) == {'ticket'}:
        _tickets.pop(params['ticket'], None)
        return {'discarded': True}
    raise ValueError('Unsupported library operation')
