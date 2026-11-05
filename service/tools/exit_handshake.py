"""Native exit is acknowledged only after admission and owned work are drained."""

import asyncio
import os
from pathlib import Path

import httpx



async def watch(workers, checks, runs):
    directory = os.environ.get('CALABASH_SELECTION_DIR')
    if not directory:
        return
    directory = Path(directory)
    while not (directory / 'stop-jobs').exists():
        await asyncio.sleep(.1)
    workers.stopping = True
    await runs.close()
    await checks.close()
    while True:
        try:
            if await workers.prepare_exit():
                break
        except (httpx.HTTPError, ValueError):
            from core.logger import get_logger
            get_logger(__name__).warning('Waiting for tool safe-exit acknowledgement')
        await asyncio.sleep(.2)
    await workers.shutdown()
    temporary = directory / '.exit-ready.tmp'
    temporary.write_text('ready', encoding='utf-8')
    temporary.replace(directory / 'exit-ready')
