"""Per-page tool runs, bounded log retention and resource ownership."""
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

from loguru import logger

from core.local_paths import app_dir, logs_dir

KEEP_RUNS = 5
MAX_AGE = 7 * 86400
MAX_RUN_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
_current = ContextVar('calabash_log_run', default=None)
_active = {}


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
    try:
        from nicegui import ui
        return getattr(ui.context.client, 'calabash_log_run', None)
    except (RuntimeError, AttributeError):
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
        cleanup()


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
    cleanup()
    return run


def retain_current(run_id=None):
    run = _active.get(run_id or current_id())
    if run:
        run.retain()
    return run


def protected_runs():
    protected = set(_active)
    # Read-only application-owned repair records. Do not initialize/migrate DBs.
    database = app_dir() / 'conversations.db'
    if database.is_file() and not database.is_symlink():
        try:
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
                rows = db.execute("SELECT json_extract(data,'$.log_run_id') FROM tool_repairs WHERE state='queued' OR (state='running' AND started > datetime('now','-10 minutes'))")
                protected.update(row[0] for row in rows if row[0])
        except sqlite3.OperationalError as error:
            if 'no such table' in str(error):
                return protected
            return None
        except sqlite3.Error:
            # Fail closed if repair ownership cannot be determined.
            return None
    return protected


def cleanup(*, now=None):
    try:
        _cleanup(now=now)
    except OSError:
        logger.warning('Tool run log cleanup deferred; filesystem is temporarily unavailable')


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
