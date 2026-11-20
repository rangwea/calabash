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
    if method == 'schedules.action' and set(params) == {'operation', 'arguments'}:
        from service.tools.tool_schedules import schedules
        return await schedules.dispatch(params['operation'], params['arguments'])
    if method == 'ai.pending' and not params:
        from service.tools.ai_host import pending
        return await pending()
    if method == 'ai.control' and set(params) == {'worker_id', 'request_id', 'digest', 'operation', 'lease', 'text'}:
        from service.tools.ai_host import control
        return await control(**params)
    if method == 'app.active_tasks' and not params:
        for worker in tuple(workers.items.values()):
            if worker.active_calls or worker.alive and (await workers.status(worker)).get('running'):
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
        if method == 'workspace.binding' and set(params) == {'session'}:
            return workspace.binding(params['session'])
        if method == 'workspace.check_preview' and set(params) == {'session'}:
            return await workspace.check_preview(params['session'])
        if method == 'workspace.verification' and set(params) == {'session'}:
            return await workspace.preview_diagnostics(params['session'])
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
    if method == 'actions.catalog' and not params:
        from service.actions.registry import catalog
        return catalog()['actions']
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
        from service.tools.tool_schedules import schedules
        schedules.stop()
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
    original_stdout = sys.stdout
    if writer is None:
        writer = sys.stdout
        sys.stdout = sys.stderr
    ensure_local_dirs()
    import anyio.to_thread

    from service.tools.tool_schedules import schedules
    anyio.to_thread.current_default_thread_limiter().total_tokens = 4
    schedules.start()
    schedule_loop = asyncio.create_task(schedules.run())
    monitor = asyncio.create_task(workers.monitor())
    pending = set()
    locks = {}

    def resource(method, params):
        if method == 'agent.call':
            return ('session', params.get('session'))
        if method == 'library.action' and params.get('operation') == 'conversation':
            session = params.get('arguments', {}).get('session')
            return ('session', session) if session else None
        if method in {'agent.release', 'workspace.preview', 'workspace.publish'}:
            from service.tools import harness_workspace as workspace
            target = workspace.state(params.get('session'))
            return ('tool', target['project'], target['name']) if target else ('session', params.get('session'))
        if method.startswith('tools.') and 'project' in params:
            return ('tool', params['project'], params.get('name'))
        return None

    async def respond(request):
        request_id = request.get('id')
        try:
            method, params = request['method'], request['params']
            if not isinstance(method, str) or not isinstance(params, dict):
                raise TypeError('Invalid request')
            key = resource(method, params)
            if key:
                async with locks.setdefault(key, asyncio.Lock()):
                    result = await dispatch(method, params)
            else:
                result = await dispatch(method, params)
            response = {'id': request_id, 'result': result}
        except Exception:
            if request.get('method', '').startswith('ai.'):
                logger.warning('AI host operation unavailable')
            else:
                logger.exception('Harness tool operation failed')
            response = {'id': request_id, 'error': {'code': 'operation_failed', 'message': 'Unable to complete this tool operation.'}}
        writer.write(json.dumps(response, ensure_ascii=False) + '\n')
        writer.flush()

    try:
        while True:
            line = await asyncio.to_thread(reader.readline, MAX_REQUEST + 1)
            if not line or len(line) > MAX_REQUEST or not line.endswith(b'\n'):
                break
            try:
                request = json.loads(line)
                if not isinstance(request, dict) or set(request) != {'id', 'method', 'params'}:
                    raise ValueError('Invalid request envelope')
                if not isinstance(request['id'], str) or not 1 <= len(request['id']) <= 80:
                    raise ValueError('Invalid request identifier')
            except (ValueError, TypeError):
                writer.write(json.dumps({'id': None, 'error': {'code': 'operation_failed', 'message': 'Invalid request'}}) + '\n')
                writer.flush()
                continue
            if request['method'] == 'app.prepare_exit':
                await asyncio.gather(*pending, return_exceptions=True)
                await respond(request)
                continue
            if len(pending) >= 32:
                writer.write(json.dumps({'id': request['id'], 'error': {'code': 'busy', 'message': 'Please retry shortly'}}) + '\n')
                writer.flush()
                continue
            task = asyncio.create_task(respond(request))
            pending.add(task)
            task.add_done_callback(pending.discard)
    finally:
        schedules.stop()
        # A disconnected renderer/host does not cancel a source write or business file operation.
        await asyncio.gather(*pending, return_exceptions=True)
        while not await workers.prepare_exit():
            await asyncio.sleep(.25)
        from service.tools import harness_workspace as workspace
        workspace.release_all()
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)
        await schedule_loop
        await workers.shutdown()
        from service.tools.tool_checks import checks
        await checks.close()
        sys.stdout = original_stdout


if __name__ == '__main__':
    asyncio.run(serve())
