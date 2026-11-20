"""Versioned React/Python source bundles. Reading/importing never executes code."""

import ast
import hashlib
import io
import json
import os
import re
import shutil
import stat
import threading
from pathlib import Path, PurePosixPath
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from core.local_paths import app_dir, tools_dir
from service.tools.source_integrity import validate_source_file

MAX_FILE = 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_FILES = 100
RUNTIME_ENTRIES = frozenset({'data.sqlite', 'data.sqlite-journal', 'data.sqlite-wal', 'data.sqlite-shm', 'inputs', 'outputs'})
_lock = threading.RLock()


class ToolUnavailable(ValueError):
    def __init__(self):
        self.code = 'tool_not_found'
        super().__init__('No React draft or published tool exists. List tools or create a new React draft; do not guess source paths.')


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', value):
        raise ValueError('Invalid tool identity')
    return value


def safe_path(value):
    if not isinstance(value, str) or '\\' in value or '\x00' in value or ':' in value:
        raise ValueError('Invalid tool path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {'..', '.', 'node_modules', 'dist', '.git'} for part in value.split('/')):
        raise ValueError('Invalid tool path')
    if any(not part or part.rstrip('. ') != part for part in value.split('/')):
        raise ValueError('Invalid tool path')
    if value != 'tool.json' and not (value.startswith('frontend/') and path.suffix in {'.tsx', '.ts', '.css', '.json'} or value.startswith('backend/') and path.suffix == '.py'):
        raise ValueError('Unsupported tool source')
    return value


def revision(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate(files, project=None, name=None, *, check_source=True):
    if not isinstance(files, dict) or not 3 <= len(files) <= MAX_FILES:
        raise ValueError('Invalid tool files')
    total = 0
    names = set()
    for path, content in files.items():
        safe_path(path)
        if path.casefold() in names:
            raise ValueError('Tool paths must be distinct on every supported platform')
        names.add(path.casefold())
        if not isinstance(content, str) or len(content.encode()) > MAX_FILE:
            raise ValueError('Tool file too large')
        if check_source:
            validate_source_file(path, content)
        total += len(content.encode())
        if path.endswith('.py'):
            ast.parse(content, filename=path)
    if total > MAX_TOTAL:
        raise ValueError('Tool bundle too large')
    manifest = validate_manifest(files, project, name)
    if not files.get('frontend/App.tsx') or not files.get('backend/main.py'):
        raise ValueError('App.tsx and backend/main.py are required')
    tree = ast.parse(files['backend/main.py'])
    if not any(isinstance(node, ast.FunctionDef) and node.name == 'setup' for node in tree.body):
        raise ValueError('Backend must define setup(app, sdk), without starting a server')
    return manifest


def validate_manifest(files, project=None, name=None):
    manifest = json.loads(files.get('tool.json', '{}'))
    if not isinstance(manifest, dict):
        raise ValueError('tool.json must be an object')  # noqa: TRY004 - bounded source-validation errors use ValueError.
    if manifest.get('format') != 'calabash-react-tool' or manifest.get('version') != 1:
        raise ValueError('Unsupported tool format')
    for key in ('project', 'name'):
        identity(manifest.get(key))
    if project is not None and (manifest['project'], manifest['name']) != (project, name):
        raise ValueError('Tool identity mismatch')
    for key, maximum in (('title', 200), ('description', 2000), ('requires', 1000)):
        if not isinstance(manifest.get(key, ''), str) or len(manifest.get(key, '')) > maximum:
            raise ValueError('Invalid tool metadata')
    if 'ui' in manifest:
        ui = manifest['ui']
        if not isinstance(ui, dict) or set(ui) != {'preset', 'version'} or not isinstance(ui['preset'], str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', ui['preset']) or type(ui['version']) is not int or ui['version'] < 1:
            raise ValueError('Invalid UI preset metadata')
        if not files.get('frontend/calabash-theme.css'):
            raise ValueError('UI preset token snapshot is required')
    from service.capabilities.tool_capabilities import parse_requirements
    parse_requirements(manifest.get('requires', ''))
    return manifest


def directory(project, name, chat_id=None):
    identity(project); identity(name)
    root = tools_dir() if chat_id is None else app_dir() / 'drafts'
    if chat_id is not None:
        identity(chat_id)
    path = root / project / name
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError('Symlink tool paths are forbidden')
        if part == root:
            break
    return path


def read_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Symlink tool paths are forbidden')
    if not (path / 'tool.json').is_file():
        raise ToolUnavailable()
    files = {}
    for current, directories, names in os.walk(path, followlinks=False):
        current = Path(current)
        for name in list(directories):
            item = current / name
            if item.is_symlink():
                raise ValueError('Symlink tool files are forbidden')
            if current == path and (name in RUNTIME_ENTRIES or name == 'dist'):
                directories.remove(name)
        for name in names:
            if current == path and name in RUNTIME_ENTRIES:
                continue
            item = current / name
            if item.is_symlink():
                raise ValueError('Symlink tool files are forbidden')
            relative = item.relative_to(path).as_posix()
            safe_path(relative)
            if item.stat().st_size > MAX_FILE or len(files) >= MAX_FILES:
                raise ValueError('Tool bundle too large')
            files[relative] = item.read_text(encoding='utf-8')
    validate(files, check_source=False)
    return files


def read(project, name, chat_id=None):
    if chat_id is not None and directory(project, name, chat_id).exists():
        from service.tools.work_drafts import snapshot
        return snapshot(project, name)
    path = directory(project, name, chat_id)
    if not path.is_dir() and chat_id:
        path = directory(project, name)
    if not path.is_dir():
        raise ToolUnavailable()
    files = read_directory(path)
    return {'files': files, 'revision': revision(files), 'source': 'preview' if chat_id and path == directory(project, name, chat_id) else 'published'}


def write(project, name, files, expected='', chat_id=None, built_dist=None):
    validate(files, project, name)
    path = directory(project, name, chat_id)
    with _lock:
        current = revision(read_directory(path)) if (path / 'tool.json').is_file() else ''
        if current != expected:
            raise ValueError('Source changed; read current revision before writing')
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name('.' + path.name + '-' + uuid4().hex)
        backup = path.with_name('.' + path.name + '-backup-' + uuid4().hex)
        completed = False
        try:
            temporary.mkdir(mode=0o700)
            for relative, content in files.items():
                destination = temporary / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding='utf-8')
            if built_dist is not None:
                shutil.copytree(built_dist, temporary / 'dist')
            if path.exists():
                # Replace source entries only; database files, live journals
                # and input/output directories stay at their original paths.
                backup.mkdir(mode=0o700)
                moved, installed = [], []
                try:
                    for entry in list(path.iterdir()):
                        if entry.name in {'tool.json', 'frontend', 'backend', 'dist'}:
                            entry.rename(backup / entry.name)
                            moved.append(entry.name)
                    for entry in list(temporary.iterdir()):
                        entry.rename(path / entry.name)
                        installed.append(entry.name)
                except BaseException:
                    for entry_name in reversed(installed):
                        (path / entry_name).rename(temporary / entry_name)
                    for entry_name in reversed(moved):
                        (backup / entry_name).rename(path / entry_name)
                    raise
            else:
                temporary.rename(path)
            completed = True
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
            if backup.exists() and (completed or not any(backup.iterdir())):
                shutil.rmtree(backup)
    return {'revision': revision(files), 'source': 'preview' if chat_id else 'published'}


def list_tools():
    result = []
    for path in tools_dir().glob('*/*/tool.json'):
        if any(part.startswith('.') for part in path.relative_to(tools_dir()).parts):
            continue
        try:
            source = read(path.parent.parent.name, path.parent.name)
            meta = validate(source['files'])
            result.append({**meta, 'title': meta.get('title', meta['name']), 'description': meta.get('description', ''), 'revision': source['revision']})
        except (ValueError, OSError, SyntaxError):
            continue
    return result


def export_zip(project, name):
    data = read(project, name)
    # Published source holds restored credentials: authoring replaces real secrets
    # with placeholders only in memory. A shared ZIP must never carry them.
    from service.tools.source_credentials import strip_credentials
    stream = io.BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as archive:
        for path, content in data['files'].items():
            archive.writestr(path, strip_credentials(content) if path.endswith(('.py', '.tsx', '.ts', '.json', '.css')) else content)
    return stream.getvalue()


def inspect_zip(data):
    if len(data) > MAX_TOTAL:
        raise ValueError('Archive too large')
    files = {}
    with ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > MAX_FILES:
            raise ValueError('Too many files')
        if sum(info.file_size for info in archive.infolist()) > MAX_TOTAL:
            raise ValueError('Archive expands beyond limit')
        for info in archive.infolist():
            safe_path(info.filename)
            mode = info.external_attr >> 16
            if info.filename in files or info.is_dir() or info.flag_bits & 1 or stat.S_IFMT(mode) not in {0, stat.S_IFREG} or info.file_size > MAX_FILE:
                raise ValueError('Invalid archive entry')
            files[info.filename] = archive.read(info).decode('utf-8')
    validate(files)
    return files


def delete(project, name, expected):
    from service.tools.tool_workers import workers
    path = directory(project, name)
    with _lock:
        if workers.is_open(project, name):
            raise ValueError('Close the tool before deleting')
        if revision(read_directory(path)) != expected:
            raise ValueError('Source changed')
        # Move to recoverable application trash, never touch neighboring files.
        trash = app_dir() / 'trash'
        trash.mkdir(parents=True, exist_ok=True)
        path.rename(trash / f'{project}-{name}-{uuid4().hex}')
