"""Scoped, consent-gated access to actual tool logs."""
import os
import re
import hashlib
import traceback
from pathlib import Path

MAX_LOG_BYTES = 262144
MAX_PAGE_CHARS = 16000

def target_path(report):
    from service.chat import ai_chat
    path = ai_chat.tool_path(report['project'], report['name'])
    raw_path = ai_chat.tools_dir() / report['project'] / f"{report['name']}.py"
    if raw_path.is_symlink() or raw_path.parent.is_symlink():
        raise ValueError('Diagnostic source is unavailable')
    if report.get('preview_key'):
        from service.tools import preview_service
        from service.files import tool_inputs
        if tool_inputs.owner(report.get('context'), report['preview_key'])[0] != f"tool:{report['project']}/{report['name']}":
            raise ValueError('Unbound diagnostic source')
        path = preview_service.get_preview_file(report['preview_key'])
    if path.is_symlink():
        raise ValueError('Diagnostic source is unavailable')
    return path


def current_revision(report):
    return hashlib.sha256(target_path(report).read_bytes()).hexdigest()


def is_latest(report):
    from contextlib import closing
    from service.chat import ai_chat
    with closing(ai_chat.connect()) as db:
        row = db.execute("""SELECT id FROM tool_repairs WHERE
            json_extract(data,'$.project')=? AND json_extract(data,'$.name')=?
            AND json_extract(data,'$.preview_key') IS ?
            AND json_extract(data,'$.log_run_id')=? ORDER BY rowid DESC LIMIT 1""",
            (report['project'], report['name'], report.get('preview_key'), report['log_run_id'])).fetchone()
    return bool(row and row[0] == report['id'])


def log_path(report):
    from core import tool_run_logs
    path = tool_run_logs.directory(report['project'], report['name'], report['log_run_id']) / 'tool.log'
    if path.is_symlink():
        raise ValueError('Symlink log targets are not allowed')
    return path


def record_failure(report, error):
    # Persist a real traceback without locals or source-line expansion. This also
    # covers preflight errors that occur before the normal tool logger is mounted.
    path = log_path(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    trace = traceback.TracebackException.from_exception(error, lookup_lines=False, capture_locals=False)
    pending = [trace]
    while pending:
        item = pending.pop()
        item.stack = traceback.StackSummary.from_list([
            traceback.FrameSummary(frame.filename, frame.lineno, frame.name, line='', lookup_line=False)
            for frame in item.stack
        ])
        pending.extend(part for part in (item.__cause__, item.__context__) if part is not None)
        pending.extend(item.exceptions or [])
    text = '\n--- Calabash repair failure ' + report['captured_at'] + ' ---\n' + ''.join(trace.format())
    from core import tool_run_logs
    run = tool_run_logs._active.get(report['log_run_id'])
    if run is None:
        raise ValueError('Log run is no longer active')
    return run.writer.append(text, snapshot=True)


def read(report, *, offset=0, limit=80, query=''):
    from service.tools.tool_repairs import RepairSession
    revision = current_revision(report)
    result = {'log_run_id': report['log_run_id'], 'source': 'preview' if report.get('preview_key') else 'published',
              'current_revision': revision, 'captured_revision': report['revision'],
              'matches_current_code': revision == report['revision'], 'executed': False}
    if not is_latest(report):
        return {**result, 'status': 'superseded'}
    if revision != report['revision']:
        return {**result, 'status': 'code_changed'}
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100 or not isinstance(query, str) or len(query) > 200:
        raise ValueError('Invalid log pagination or search')
    window = report['log_window']
    path = log_path(report)
    # Rotation may move the captured file while this page continues running.
    if path.exists() and path.stat().st_ino != window['inode']:
        rotated = path.with_name('tool.1.log')
        if rotated.is_file() and not rotated.is_symlink() and rotated.stat().st_ino == window['inode']:
            path = rotated
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino) != (window['device'], window['inode']) or info.st_size < window['end']:
            return {**result, 'status': 'log_changed', 'next_action': 'Retry manually to capture a fresh failure.'}
        stream.seek(window['start'])
        raw = stream.read(window['end'] - window['start'])
        if hashlib.sha256(raw).hexdigest() != window['digest']:
            return {**result, 'status': 'log_changed', 'next_action': 'Retry manually to capture a fresh failure.'}
        text = raw.decode('utf-8', errors='replace')
    redactor = RepairSession(report)
    redactor.redact(target_path(report).read_text(encoding='utf-8'))
    from service.chat import model_providers
    secrets = list(redactor.secrets.values()) + [c.get('key') for c in model_providers.load()['connections'].values()]
    for secret in sorted({v for v in secrets if isinstance(v, str) and v}, key=len, reverse=True):
        text = text.replace(secret, '[CREDENTIAL REDACTED]')
    text = re.sub(r'(?i)(bearer\s+|(?:api[_-]?key|password|secret|token|authorization)\s*[:=]\s*)[^\s,;]+', r'\1[CREDENTIAL REDACTED]', text)
    text = re.sub(r'[^\x09\x0a\x0d\x20-\U0010ffff]', '', text)
    lines = text.splitlines()
    # Skip a partial first line when reading a bounded tail.
    if window['start']:
        lines = lines[1:]
    matches = [(n + 1, line) for n, line in enumerate(lines) if not query or query.casefold() in line.casefold()]
    page, size, cursor = [], 0, offset
    for number, line in matches[offset:offset + limit]:
        line = line[:MAX_PAGE_CHARS]
        if page and size + len(line) > MAX_PAGE_CHARS:
            break
        page.append({'line': number, 'text': line})
        size += len(line)
        cursor += 1
    return {**result, 'status': 'current', 'untrusted_log_lines': page,
            'offset': offset, 'next_offset': cursor if cursor < len(matches) else None,
            'matching_lines': len(matches), 'bounded_tail': bool(window['start']),
            'captured_at': report['captured_at'], 'query': query}
