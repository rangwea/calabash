"""Cancellation-safe creation and bounded cleanup of host-owned subprocesses."""

import asyncio
import os
import signal
import subprocess
import time


def stop(process, *, group=False, timeout=5):
    """Reap the leader and, on POSIX, its explicitly owned process group."""
    def send(force=False):
        try:
            if group and os.name == 'posix':
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            elif process.poll() is None:
                process.kill() if force else process.terminate()
        except ProcessLookupError:
            pass

    if group and os.name == 'nt' and process.stdin:
        # The trusted Node runner drains its checker/server on host-pipe EOF.
        process.stdin.close()
    else:
        send()
    deadline = time.monotonic() + timeout
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    if group and os.name == 'posix':
        # A leader exiting does not imply its compiler children exited.
        while time.monotonic() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                if process.stdin:
                    process.stdin.close()
                return
            time.sleep(.05)
    send(force=True)
    process.wait()
    if process.stdin:
        process.stdin.close()


async def spawn(args, *, group=False, **kwargs):
    if group and os.name == 'posix':
        kwargs['start_new_session'] = True
    pending = asyncio.create_task(asyncio.to_thread(subprocess.Popen, args, **kwargs))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        # Popen in a thread can succeed after its caller has been cancelled.
        process = await pending
        await asyncio.to_thread(stop, process, group=group)
        raise
