"""Host-only AI control, resolved against the executor's live worker ownership."""
import httpx

from service.tools import tool_bundles as bundles
from service.tools.tool_workers import workers


async def _request(worker, path, body=None):
    async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
        headers = {'Authorization': 'Bearer ' + worker.token, 'X-Calabash-Host': worker.host_token}
        url = f'http://127.0.0.1:{worker.port}/api/sdk/ai/{path}'
        response = await client.get(url, headers=headers) if body is None else await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()


def _current(worker, key):
    if workers.stopping or not worker.alive:
        return False
    try:
        return bundles.read(worker.project, worker.name, key[2])['revision'] == worker.revision
    except (ValueError, OSError):
        return False


async def pending():
    result = []
    for key, worker in tuple(workers.items.items()):
        if not worker.alive:
            continue
        try:
            entries = await _request(worker, 'requests')
            if entries and not _current(worker, key):
                for entry in entries:
                    await _request(worker, 'control', {'operation': 'reject', 'request_id': entry['request_id'], 'digest': entry['digest']})
                continue
            for entry in entries[:1]:
                if entry['worker_id'] != worker.root.name or entry['revision'] != worker.revision:
                    continue
                result.append({**entry, 'project': worker.project, 'name': worker.name})
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            continue
    return result[:32]


async def control(worker_id, request_id, digest, operation, lease='', text=''):
    if not isinstance(worker_id, str) or len(worker_id) != 32:
        raise ValueError('AI worker unavailable')
    for key, worker in tuple(workers.items.items()):
        if worker.root.name != worker_id:
            continue
        if not _current(worker, key):
            # Revoke a now-stale waiting/running request without sending its contents.
            try:
                await _request(worker, 'control', {'operation': 'reject', 'request_id': request_id, 'digest': digest})
            except (httpx.HTTPError, ValueError):
                pass
            raise ValueError('AI source changed') from None
        return await _request(worker, 'control', {'request_id': request_id, 'digest': digest, 'operation': operation, 'lease': lease, 'text': text})
    raise ValueError('AI worker unavailable')
