"""Per-page tool runs, bounded log retention and resource ownership."""
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

from loguru import logger

from core.local_paths import logs_dir

KEEP_RUNS = 5
MAX_AGE = 7 * 86400
MAX_RUN_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
_current = ContextVar('calabash_log_run', default=None)
_active = {}
# One background worker: retention cleanup is idempotent and must never queue up.
_CLEANUP_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='calabash-log-cleanup')
_last_cleanup = None


def root():
    return logs_dir() / 'runs'


def _part(value):
    if not isinstance(value, str) or value in {'.', '..'} or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', value):
        raise ValueError('Invalid log identity')
    return value


def directory(project, name, run_id):
    if not re.fullmatch(r'[a-f0-9]{32}', run_id or ''):
        raise ValueError('Invalid log run')
    path = root() / _part(project) / _part(name) / run_id
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('Symlink log directory is not allowed')
        if item == root():
            break
    return path


def current_id():
    value = _current.get()
    if value:
        return value
    return None


def add_context(record):
    if not record['extra'].get('tool_run_id'):
        value = current_id()
        if value:
            record['extra']['tool_run_id'] = value


class ModuleHandler(logging.Handler):
    def __init__(self, run_id):
        super().__init__()
        self.run_id = run_id

    def emit(self, record):
        logger.bind(tool_run_id=self.run_id).opt(exception=record.exc_info).log(record.levelno, record.getMessage())


class BoundedSink:
    """Current + one rotated file, bounded even for one enormous log event."""
    def __init__(self, folder):
        self.folder = folder
        self.lock = threading.RLock()

    def append(self, text, *, snapshot=False):
        data = str(text).encode('utf-8', errors='replace')
        cap = MAX_RUN_BYTES // 2
        if len(data) > cap:
            data = b'[Log entry truncated]\n' + data[-(cap - 64):]
        with self.lock:
            path = self.folder / 'tool.log'
            rotated = self.folder / 'tool.1.log'
            if path.is_symlink() or rotated.is_symlink():
                raise ValueError('Symlink log targets are not allowed')
            if path.exists() and path.stat().st_size + len(data) > cap:
                path.replace(rotated)
            fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'a+b') as stream:
                stream.write(data)
                stream.flush()
                if not snapshot:
                    return
                info = os.fstat(stream.fileno())
                start = max(0, info.st_size - 262144)
                stream.seek(start)
                digest = hashlib.sha256(stream.read(info.st_size - start)).hexdigest()
                return {'digest': digest, 'end': info.st_size, 'start': start,
                        'device': info.st_dev, 'inode': info.st_ino}

    def write(self, message):
        self.append(message)


@dataclass
class Run:
    id: str
    project: str
    name: str
    preview_key: str | None
    sink: int
    writer: BoundedSink
    references: int = 1
    handlers: list = field(default_factory=list)

    @property
    def path(self):
        return directory(self.project, self.name, self.id) / 'tool.log'

    @property
    def logger(self):
        return logger.bind(tool_run_id=self.id)

    @contextmanager
    def context(self):
        token = _current.set(self.id)
        try:
            with logger.contextualize(tool_run_id=self.id):
                yield
        finally:
            _current.reset(token)

    def attach_module(self, module_name):
        target = logging.getLogger(module_name)
        handler = ModuleHandler(self.id)
        self.handlers.append((target, handler, target.level, target.propagate))
        target.addHandler(handler)
        target.setLevel(logging.DEBUG)
        target.propagate = False

    def retain(self):
        if self.references == 0:
            if not self.path.is_file() or self.path.is_symlink():
                raise ValueError('Run logs are no longer available')
            self.sink = logger.add(self.writer, format='{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}',
                                   filter=lambda record: record['extra'].get('tool_run_id') == self.id,
                                   backtrace=False, diagnose=False)
            _active[self.id] = self
        self.references += 1

    def close(self):
        if self.references <= 0:
            return
        self.references -= 1
        if self.references:
            return
        for target, handler, level, propagate in self.handlers:
            target.removeHandler(handler)
            handler.close()
            target.setLevel(level)
            target.propagate = propagate
        for target, _, _, _ in self.handlers:
            if not target.handlers and logging.Logger.manager.loggerDict.get(target.name) is target:
                logging.Logger.manager.loggerDict.pop(target.name, None)
        self.handlers.clear()
        logger.remove(self.sink)
        _active.pop(self.id, None)
        # Retention cleanup walks and removes whole run trees. Running it inline
        # would stall every tool request on the event loop, so it goes to a thread.
        schedule_cleanup()


def start(project, name, *, preview_key=None, client=None):
    run_id = uuid4().hex
    folder = directory(project, name, run_id)
    folder.mkdir(parents=True, exist_ok=False)
    folder.chmod(0o700)
    metadata = {'id': run_id, 'project': project, 'name': name, 'preview_key': preview_key, 'created': time.time()}
    (folder / 'run.json').write_text(json.dumps(metadata), encoding='utf-8')
    # Two files per run: current plus one rotated file, 5 MiB combined.
    writer = BoundedSink(folder)
    writer.write(f"Run {run_id} started\n")
    sink = logger.add(writer, format='{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}',
                      filter=lambda record: record['extra'].get('tool_run_id') == run_id,
                      backtrace=False, diagnose=False)
    run = Run(run_id, project, name, preview_key, sink, writer)
    _active[run_id] = run
    if client is not None:
        client.calabash_log_run = run_id
        client.on_delete(run.close)
    schedule_cleanup()
    return run


def retain_current(run_id=None):
    run = _active.get(run_id or current_id())
    if run:
        run.retain()
    return run


def protected_runs():
    # Worker and consent grants retain the public Run object until completion.
    return set(_active)


def cleanup(*, now=None):
    try:
        _cleanup(now=now)
    except OSError:
        logger.warning('Tool run log cleanup deferred; filesystem is temporarily unavailable')


def schedule_cleanup(*, now=None):
    """Retention cleanup without blocking the caller's event loop."""
    global _last_cleanup
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        cleanup(now=now)
        return
    _last_cleanup = _CLEANUP_EXECUTOR.submit(cleanup, now=now)


async def flush(*, now=None):
    """Await the most recently scheduled cleanup; tests and shutdown only."""
    if now is not None:
        schedule_cleanup(now=now)
        future = _last_cleanup
        if future is not None:
            await asyncio.wrap_future(future)
        return
    while _last_cleanup is not None and not _last_cleanup.done():
        await asyncio.wrap_future(_last_cleanup)


def _cleanup(*, now=None):
    base = root()
    if not base.exists() or base.is_symlink():
        return
    protected = protected_runs()
    if protected is None:
        return
    now = time.time() if now is None else now
    groups = {}
    for project in base.iterdir():
        if not project.is_dir() or project.is_symlink():
            continue
        for tool in project.iterdir():
            if not tool.is_dir() or tool.is_symlink():
                continue
            entries = []
            for folder in tool.iterdir():
                if folder.is_symlink() or not folder.is_dir() or not re.fullmatch(r'[a-f0-9]{32}', folder.name):
                    continue
                files = list(folder.iterdir())
                # Never traverse unknown subdirectories or symlink payloads.
                if any(item.is_symlink() or not item.is_file() for item in files):
                    continue
                try:
                    metadata = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
                    if (metadata['id'], metadata['project'], metadata['name']) != (folder.name, project.name, tool.name):
                        continue
                    created = float(metadata['created'])
                    size = sum(item.stat().st_size for item in files)
                except (OSError, ValueError, KeyError, TypeError):
                    continue
                entries.append((folder, created, size))
            groups[tool] = sorted(entries, key=lambda item: item[1], reverse=True)
    remaining = []
    for entries in groups.values():
        for index, (folder, modified, size) in enumerate(entries):
            if folder.name not in protected and (index >= KEEP_RUNS or now - modified > MAX_AGE):
                try:
                    shutil.rmtree(folder)
                except OSError:
                    remaining.append((folder, modified, size))
            else:
                remaining.append((folder, modified, size))
    total = sum(size for _, _, size in remaining)
    for folder, _, size in sorted(remaining, key=lambda item: item[1]):
        if total <= MAX_TOTAL_BYTES:
            break
        if folder.name not in protected:
            try:
                shutil.rmtree(folder)
                total -= size
            except OSError:
                continue
    for tool in groups:
        try:
            tool.rmdir()
        except OSError:
            pass
    for project in {tool.parent for tool in groups}:
        try:
            project.rmdir()
        except OSError:
            pass


def latest_preview(preview_key):
    matches = []
    if root().is_symlink():
        return None
    for marker in root().glob('*/*/*/run.json'):
        try:
            if marker.is_symlink():
                continue
            folder = directory(marker.parents[2].name, marker.parents[1].name, marker.parent.name)
            info = json.loads(marker.read_text(encoding='utf-8'))
            if marker != folder / 'run.json' or info.get('preview_key') != preview_key:
                continue
            path = folder / 'tool.log'
            if path.is_file() and not path.is_symlink():
                matches.append((info['created'], path))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return max(matches, key=lambda item: item[0])[1] if matches else None
