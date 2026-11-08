"""Process-local task admission and safe cancellation. Cross-process exit uses ToolSDK."""


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
    _active[key] = jobs


def release(jobs):
    key = jobs.owner or id(jobs)
    if _active.get(key) is jobs:
        del _active[key]
