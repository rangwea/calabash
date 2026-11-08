"""One real authoring directory per tool; fingerprints and leases stay host-owned."""
import hashlib
import os
import stat
import threading
from contextlib import contextmanager
from uuid import uuid4

from core.local_paths import app_dir
from service.tools import operation_store
from service.tools import tool_bundles as bundles
from service.tools.source_integrity import validate_source_file

_mutex = threading.RLock()
_leases = {}


def fingerprint(content):
    return hashlib.sha256(content.encode()).hexdigest()


@contextmanager
def _os_lock(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    handle = os.fdopen(fd, 'r+b')
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
            raise ValueError('Invalid workspace lock')
        if os.name == 'nt':
            import msvcrt
            handle.write(b'0'); handle.flush(); handle.seek(0)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except OSError as error:
        raise ValueError('This tool is being edited in another conversation. Wait for that task to finish.') from error
    finally:
        if os.name == 'nt':
            try:
                handle.seek(0); msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        handle.close()


def claim(project, name, run_id):
    bundles.identity(project); bundles.identity(name); bundles.identity(run_id)
    key = (str(app_dir()), project, name)
    with _mutex:
        current = _leases.get(key)
        if current:
            if current[0] != run_id:
                raise ValueError('This tool is being edited in another conversation. Wait for that task to finish.')
            return
        path = app_dir() / 'agent/draft_locks' / project / (name + '.lock')
        _safe(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        context = _os_lock(path)
        context.__enter__()
        _leases[key] = (run_id, context)


def release(run_id):
    with _mutex:
        for key, (owner, context) in list(_leases.items()):
            if owner == run_id:
                context.__exit__(None, None, None)
                del _leases[key]


def _safe(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Symlink workspace paths are forbidden')
        if part == app_dir():
            break
    if path.is_file() and path.stat().st_nlink != 1:
        raise ValueError('Linked workspace files are forbidden')


def snapshot(project, name):
    with _mutex:
        return _snapshot(project, name)


def _snapshot(project, name):
    root = bundles.directory(project, name, 'workspace')
    if not root.is_dir():
        raise bundles.ToolUnavailable()
    files, total = {}, 0
    for path in sorted(root.rglob('*')):
        _safe(path)
        if '__pycache__' in path.relative_to(root).parts:
            continue
        if path.is_file():
            relative = bundles.safe_path(path.relative_to(root).as_posix())
            if path.stat().st_size > bundles.MAX_FILE or len(files) >= bundles.MAX_FILES:
                raise ValueError('Workspace source exceeds limits')
            content = path.read_text(encoding='utf-8')
            total += len(content.encode())
            if total > bundles.MAX_TOTAL:
                raise ValueError('Workspace source exceeds limits')
            files[relative] = content
    return {'files': files, 'revision': bundles.revision(files), 'source': 'preview'}


def ensure(project, name, run_id):
    """Copy published source once. A resumed task never overwrites working files."""
    with _mutex:
        root = bundles.directory(project, name, 'workspace')
        if not root.exists() and bundles.directory(project, name).exists():
            claim(project, name, run_id)
            source = bundles.read(project, name)
            bundles.write(project, name, source['files'], chat_id='workspace')
        return snapshot(project, name)


def observe(chat_id, project, name, path, content):
    operation_store.observe_source(chat_id, project, name, path, fingerprint(content))


def _atomic(path, content):
    _safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '-' + uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8') as output:
            temporary.chmod(0o600)
            output.write(content); output.flush(); os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_files(chat_id, run_id, project, name, changes, *, create_only=False):
    """Atomically replace each file after automatic compare-and-swap checks."""
    claim(project, name, run_id)
    with _mutex:
        root = bundles.directory(project, name, 'workspace')
        try:
            current = snapshot(project, name)['files']
        except bundles.ToolUnavailable:
            current = {}
        if create_only and current:
            raise ValueError('A working draft already exists. Read and patch its relevant file; do not replace the whole tool.')
        for path, content in changes.items():
            bundles.safe_path(path)
            if not isinstance(content, str):
                raise ValueError('Workspace source must be text')  # noqa: TRY004 - bounded source-validation errors use ValueError.
        combined = {**current, **changes}
        if len({path.casefold() for path in combined}) != len(combined):
            raise ValueError('Source paths must be distinct on every platform')
        if 'tool.json' in combined:
            bundles.validate_manifest(combined, project, name)
        if len(combined) > bundles.MAX_FILES or sum(len(text.encode()) for text in combined.values()) > bundles.MAX_TOTAL:
            raise ValueError('Workspace source exceeds limits')
        for path, content in changes.items():
            bundles.safe_path(path); _safe(root / path)
            if not isinstance(content, str) or len(content.encode()) > bundles.MAX_FILE:
                raise ValueError('Invalid workspace source')
            validate_source_file(path, content)
            if path in current and operation_store.observed_source(chat_id, project, name, path) != fingerprint(current[path]):
                raise ValueError(f'{path}: source changed or has not been read. Read this current file before editing; no revision argument is needed.')
        for path, content in changes.items():
            _atomic(root / path, content)
            observe(chat_id, project, name, path, content)
        return snapshot(project, name)
