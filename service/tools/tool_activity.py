"""In-process run ownership and native safe-exit handoff. No task persistence."""

import json
import os
from pathlib import Path
from uuid import uuid4

_active = {}
_stopping_tools = set()


def request_tool_stop(project, name):
    owner = f'tool:{project}/{name}'
    _stopping_tools.add(owner)
    for jobs in tuple(_active.values()):
        if jobs.owner == owner or getattr(jobs, 'tool_owner', None) == owner:
            jobs.cancel()


def finish_tool_stop(project, name):
    _stopping_tools.discard(f'tool:{project}/{name}')


class ToolBusyError(RuntimeError):
    def __init__(self, reason="running"):
        self.reason = reason
        super().__init__(reason)


def _directory():
    value = os.environ.get("CALABASH_SELECTION_DIR")
    return Path(value) if value else None


def _publish():
    directory = _directory()
    if directory is None:
        return
    destination = directory / "active-jobs.json"
    temporary = directory / f".jobs-{uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            temporary.chmod(0o600)
            json.dump({"active": len(_active)}, handle)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def active_count():
    return len(_active)


def is_tool_running(project, name):
    owner = f"tool:{project}/{name}"
    return any(
        jobs.owner == owner or getattr(jobs, "tool_owner", None) == owner
        for jobs in _active.values()
    )


def acquire(jobs):
    if jobs.owner in _stopping_tools or getattr(jobs, 'tool_owner', None) in _stopping_tools:
        raise ToolBusyError('stopping')
    key = jobs.owner or id(jobs)
    if key in _active:
        raise ToolBusyError()
    directory = _directory()
    if directory and (directory / "stop-jobs").exists():
        raise ToolBusyError("stopping")
    _active[key] = jobs
    try:
        _publish()
    except OSError:
        del _active[key]
        raise


def release(jobs):
    key = jobs.owner or id(jobs)
    if _active.get(key) is jobs:
        del _active[key]
    _publish()


def check_stop_request():
    directory = _directory()
    if directory and (directory / "stop-jobs").exists():
        for jobs in tuple(_active.values()):
            jobs.cancel()
