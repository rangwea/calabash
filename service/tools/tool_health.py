"""Read-only runtime snapshots. Checking a connection never starts a tool."""

import httpx

from service.tools.tool_bundles import identity
from service.tools.tool_workers import workers


async def snapshot(project, name, chat_id=None):
    identity(project)
    identity(name)
    if chat_id is not None:
        identity(chat_id)
    key = workers.key(project, name, chat_id)
    lock = workers.start_locks.get(key)
    if lock and lock.locked():
        return {'state': 'starting', 'running': None}
    worker = workers.items.get(key)
    if worker is None:
        return {'state': 'unavailable' if key in workers.failures else 'closed', 'running': False}
    origin = f'http://127.0.0.1:{worker.port}'
    if not worker.alive:
        return {'state': 'unavailable', 'running': False, 'origin': origin}
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
            response = await client.get(f'http://127.0.0.1:{worker.port}/api/sdk/status',
                                        headers={'Authorization': 'Bearer ' + worker.token})
            response.raise_for_status()
            state = response.json()
        if not isinstance(state, dict) or type(state.get('running')) is not bool:
            raise ValueError('Invalid runtime status')
    except (httpx.HTTPError, ValueError):
        return {'state': 'unavailable', 'running': None, 'origin': origin}
    frontend_ready = worker.alive
    return {'state': 'ready' if frontend_ready else 'unavailable', 'running': state['running'], 'origin': origin}
