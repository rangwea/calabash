"""Cancellation-safe creation and bounded cleanup of host-owned subprocesses."""

import asyncio
import json
import os
import signal
import subprocess
import threading
import time

_lifecycle_lock = threading.Lock()


def lifecycle(kind, pid, **values):
    if os.environ.get('CALABASH_PROCESS_CHANNEL') != '3':
        return
    packet = json.dumps({'kind': kind, 'pid': pid, **values}).encode() + b'\n'
    try:
        with _lifecycle_lock:
            os.write(3, packet)
    except (BrokenPipeError, OSError):
        # Host loss must not prevent the executor from safely draining its own children.
        pass


def stop(process, *, group=False, timeout=5):
    """Reap the leader and, on POSIX, its explicitly owned process group."""
    try:
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
    finally:
        lifecycle('stop', process.pid)


async def spawn(args, *, group=False, role='build', **kwargs):
    if group and os.name == 'posix':
        kwargs['start_new_session'] = True
    pending = asyncio.create_task(asyncio.to_thread(subprocess.Popen, args, **kwargs))
    try:
        process = await asyncio.shield(pending)
        lifecycle('start', process.pid, group=group, role=role)
        return process
    except asyncio.CancelledError:
        # Popen in a thread can succeed after its caller has been cancelled.
        process = await pending
        lifecycle('start', process.pid, group=group, role=role)
        await asyncio.to_thread(stop, process, group=group)
        raise
