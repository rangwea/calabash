"""Private stdio transport for the Electron host; never expose it to tool iframes.

The host owns source authoring separately. This transport only lists and runs
published tools, and performs the existing safe-exit handshake before disposal.
"""
import asyncio
import json
import sys
from contextlib import redirect_stdout

from core.local_paths import ensure_local_dirs

with redirect_stdout(sys.stderr):
    from core.logger import get_logger
    from service.tools import tool_bundles as bundles
    from service.tools.tool_workers import workers

logger = get_logger(__name__)
MAX_REQUEST = 2 * 1024 * 1024


async def dispatch(method, params):
    if not isinstance(params, dict):
        raise TypeError('Invalid request')
    if method == 'app.active_tasks' and not params:
        for worker in tuple(workers.items.values()):
            if worker.process.poll() is None and (await workers.status(worker)).get('running'):
                return True
        return False
    if workers.stopping and method in {'agent.call', 'tools.open', 'workspace.preview', 'workspace.publish'}:
        raise ValueError('Calabash is closing')
    if method == 'library.action' and set(params) == {'operation', 'arguments'} and isinstance(params['arguments'], dict):
        from service.tools.harness_library import dispatch as library_action
        return await library_action(params['operation'], params['arguments'])
    if method.startswith('workspace.') or method in {'agent.call', 'agent.release'}:
        from service.tools import harness_workspace as workspace
        if method == 'agent.call' and set(params) == {'session', 'call_id', 'operation', 'arguments', 'requested_preset'}:
            return await workspace.agent_call(**params)
        if method == 'agent.release' and set(params) == {'session'}:
            workspace.release(params['session'])
            return {'released': True}
        if method == 'workspace.state' and set(params) == {'session'}:
            return workspace.state(params['session'])
        if method == 'workspace.preview' and set(params) == {'session', 'refresh'} and type(params['refresh']) is bool:
            return await workspace.preview(params['session'], refresh=params['refresh'])
        if method == 'workspace.publish' and set(params) == {'session', 'expected', 'replace_revision', 'confirmed'}:
            return await workspace.publish(**params)
        if method == 'workspace.close' and set(params) == {'session'}:
            target = workspace.state(params['session'])
            if target:
                await workers.close(target['project'], target['name'], workspace.owner(params['session']))
            return {'closed': True}
        raise ValueError('Invalid workspace operation')
    if method == 'ui.presets' and not params:
        from core.i18n import translate
        from service.tools.ui_presets import catalog
        return [{**value, 'title_en': translate(value['title'], 'en'), 'description_en': translate(value['description'], 'en')} for value in catalog()]
    if method == 'tools.list':
        if params:
            raise ValueError('Unexpected arguments')
        return bundles.list_tools()
    if method == 'app.prepare_exit':
        if params:
            raise ValueError('Unexpected arguments')
        return await workers.prepare_exit()
    if method not in {'tools.open', 'tools.status', 'tools.close'}:
        raise ValueError('Unsupported operation')
    if set(params) != {'project', 'name'}:
        raise ValueError('Invalid tool arguments')
    project, name = (bundles.identity(params[key]) for key in ('project', 'name'))
    if method == 'tools.close':
        await workers.close(project, name)
        return {'closed': True}
    if method == 'tools.open':
        worker = await workers.open(project, name)
        # The host-only SDK token must never cross the renderer boundary.
        return {'url': worker.url, 'project': project, 'name': name}
    worker = workers.items.get(workers.key(project, name, None))
    return await workers.status(worker) if worker else {'running': False}


async def serve(reader=None, writer=None):
    reader = reader or sys.stdin.buffer
    writer = writer or sys.stdout
    ensure_local_dirs()
    try:
        while True:
            line = await asyncio.to_thread(reader.readline, MAX_REQUEST + 1)
            if not line:
                break
            request_id = None
            try:
                if len(line) > MAX_REQUEST or not line.endswith(b'\n'):
                    # Do not parse the tail as a second command after an oversized frame.
                    break
                request = json.loads(line)
                if not isinstance(request, dict) or set(request) != {'id', 'method', 'params'}:
                    raise ValueError('Invalid request envelope')
                request_id = request['id']
                if not isinstance(request_id, str) or not 1 <= len(request_id) <= 80:
                    raise ValueError('Invalid request identifier')
                result = await dispatch(request['method'], request['params'])
                response = {'id': request_id, 'result': result}
            except Exception:
                logger.exception('Harness tool operation failed')
                response = {'id': request_id, 'error': {'code': 'operation_failed', 'message': 'Unable to complete this tool operation.'}}
            writer.write(json.dumps(response, ensure_ascii=False) + '\n')
            writer.flush()
    finally:
        # EOF withdraws admission, but allows the current file to finish.
        while not await workers.prepare_exit():
            await asyncio.sleep(.25)
        from service.tools import harness_workspace as workspace
        workspace.release_all()
        await workers.shutdown()
        from service.tools.tool_checks import checks
        await checks.close()


if __name__ == '__main__':
    asyncio.run(serve())
