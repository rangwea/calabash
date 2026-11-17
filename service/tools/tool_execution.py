"""Shared async admission and bounded file threads; never abandon a writer."""
import asyncio
import contextvars
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import HTTPException

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='calabash-file')
_loops = weakref.WeakKeyDictionary()


class Execution:
    def __init__(self):
        self.slots = asyncio.Semaphore(2)
        self.io_slots = asyncio.Semaphore(4)
        self.locks = {}
        self.pending = 0
        self.guard = threading.Lock()

    def reserve(self):
        with self.guard:
            if self.pending >= 32:
                raise HTTPException(409, 'Task queue is full')
            self.pending += 1

    def release(self):
        with self.guard:
            self.pending -= 1

    @asynccontextmanager
    async def slot(self, owner):
        entry = self.locks.setdefault(owner, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0], self.slots:
                yield
        finally:
            entry[1] -= 1
            if not entry[1]:
                self.locks.pop(owner, None)


def execution(loop=None):
    loop = loop or asyncio.get_running_loop()
    if loop not in _loops:
        _loops[loop] = Execution()
    return _loops[loop]


async def io(function, *args, **kwargs):
    async with execution().io_slots:
        return await _io(function, *args, **kwargs)


async def _io(function, *args, **kwargs):
    context = contextvars.copy_context()
    future = asyncio.get_running_loop().run_in_executor(_pool, lambda: context.run(function, *args, **kwargs))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(future)
            break
        except asyncio.CancelledError:
            if future.done():
                future.result()
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return result
