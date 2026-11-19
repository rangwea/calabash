"""Local tool-owned build diagnostics, outside distributable source bundles."""
import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4

from core.local_paths import app_dir
from service.tools import tool_bundles as bundles


def directory(project, name, chat_id):
    for value in (project, name, chat_id):
        bundles.identity(value)
    root = app_dir() / 'diagnostics'
    path = root / project / name / 'previews' / chat_id
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Symlink diagnostic paths are forbidden')
        if part == app_dir():
            break
    return path


def record(project, name, chat_id, result, build_root=None):
    revision = result['revision']
    if len(revision) != 64 or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('Invalid diagnostic revision')
    path = directory(project, name, chat_id)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = path / f'{revision}.json'
    if target.is_symlink():
        raise ValueError('Symlink diagnostic files are forbidden')
    temporary = path / f'.{uuid4().hex}.tmp'
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            os.chmod(temporary, 0o600)
            json.dump(result, handle, ensure_ascii=False)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    if build_root:
        source = Path(build_root) / 'build.log'
        destination = path / f'{revision}.log'
        if source.is_file() and not source.is_symlink() and not destination.is_symlink():
            with source.open('rb') as handle:
                handle.seek(max(0, source.stat().st_size - 65536))
                content = handle.read(65536)
            # Compiler text is local evidence only, never returned to Agent or UI.
            with destination.open('wb') as handle:
                os.chmod(destination, 0o600)
                handle.write(content)
    candidates = sorted((p for p in path.glob('*.json') if p.is_file() and not p.is_symlink()), key=lambda p: (p == target, p.stat().st_mtime_ns, p.name), reverse=True)
    for index, item in enumerate(candidates):
        if item == target or index < 5 and time.time() - item.stat().st_mtime < 7 * 86400:
            continue
        item.unlink(missing_ok=True)
        log = item.with_suffix('.log')
        if not log.is_symlink():
            log.unlink(missing_ok=True)


def read(project, name, chat_id, revision):
    bundles.identity(revision)
    path = directory(project, name, chat_id) / f'{revision}.json'
    if not path.is_file() or path.is_symlink():
        return {'revision': revision, 'state': 'unavailable', 'diagnostics': []}
    if path.stat().st_size > 65536:
        raise ValueError('Diagnostic record too large')
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get('revision') != revision:
        raise ValueError('Diagnostic revision mismatch')
    messages = {
        'TS2322': '组件值类型不匹配，请处理空值或联合类型',
        'TS2353': '组件不支持此属性或事件，请查询组件接口',
        'TS2339': '属性不存在，请检查对象或组件接口',
        'TS2307': '无法解析模块，请使用内置库或正确的相对路径',
        'VITE': 'React 编译失败，请检查此处语法或导入',
    }
    diagnostics = []
    issues = value.get('diagnostics', [])
    for item in (issues if isinstance(issues, list) else [])[:20]:
        if not isinstance(item, dict):
            continue
        code = item.get('code', 'BUILD')
        if not isinstance(code, str) or not re.fullmatch(r'TS[0-9]{4,6}|VITE|BUILD', code):
            code = 'BUILD'
        clean = {'code': code, 'message': messages.get(code, '构建未完成，请重新检查')}
        for key in ('actual_type', 'expected_type'):
            field = item.get(key)
            if isinstance(field, str) and re.fullmatch(r'(number|string|boolean|null|undefined|unknown|never)(\[\])?', field):
                clean[key] = field
        field = item.get('property')
        if isinstance(field, str) and re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]{0,79}', field):
            clean['property'] = field
        file = item.get('file')
        if isinstance(file, str) and file.startswith('frontend/'):
            try:
                clean['file'] = bundles.safe_path(file)
            except ValueError:
                pass
        for key in ('line', 'column'):
            if type(item.get(key)) is int and 0 < item[key] < 1000000:
                clean[key] = item[key]
        diagnostics.append(clean)
    state = value.get('state')
    return {'revision': revision, 'state': state if isinstance(state, str) and state in {'passed', 'failed'} else 'unavailable', 'diagnostics': diagnostics}
