"""Local numeric request accounting. Never stores prompts, URLs, keys or errors."""

import sqlite3
from contextlib import closing
from contextvars import ContextVar

from service.chat.agent_store import root

current_run = ContextVar('calabash_usage_run', default=None)


def connect():
    path = root() / 'usage.sqlite'
    db = sqlite3.connect(path, timeout=15)
    import os
    if os.name != 'nt':
        path.chmod(0o600)
    db.execute('''CREATE TABLE IF NOT EXISTS requests (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
        provider TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
        duration_ms INTEGER NOT NULL, first_token_ms INTEGER,
        input_tokens INTEGER, output_tokens INTEGER, cached_tokens INTEGER, cache_miss_tokens INTEGER, policy_revision TEXT NOT NULL)''')
    db.commit()
    return db


def _number(value):
    return value if type(value) is int and 0 <= value <= 1_000_000_000_000 else None


def observe(packet, usage):
    """Merge provider snapshots, not token totals across successive stream events."""
    raw = packet.get('usage') or packet.get('message', {}).get('usage')
    if not isinstance(raw, dict):
        return
    aliases = {
        'input_tokens': ('input_tokens', 'prompt_tokens'),
        'output_tokens': ('output_tokens', 'completion_tokens'),
        'cached_tokens': ('prompt_cache_hit_tokens', 'cache_read_input_tokens'),
        'cache_miss_tokens': ('prompt_cache_miss_tokens',),
    }
    for key, names in aliases.items():
        for name in names:
            value = _number(raw.get(name))
            if value is not None:
                usage[key] = value
                break
    details = raw.get('prompt_tokens_details') or raw.get('input_tokens_details') or {}
    if isinstance(details, dict) and _number(details.get('cached_tokens')) is not None:
        usage['cached_tokens'] = details['cached_tokens']
    if 'prompt_cache_hit_tokens' in raw and 'prompt_cache_miss_tokens' in raw:
        hit, miss = _number(raw['prompt_cache_hit_tokens']), _number(raw['prompt_cache_miss_tokens'])
        if hit is not None and miss is not None:
            usage['input_tokens'] = hit + miss
    # Anthropic reports uncached input separately from cache read/write tokens.
    if 'input_tokens' in raw and ('cache_read_input_tokens' in raw or 'cache_creation_input_tokens' in raw):
        parts = [_number(raw.get(key, 0)) for key in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')]
        if all(value is not None for value in parts):
            usage['input_tokens'] = sum(parts)


def record(identity, run_id, kind, provider, model, status, duration_ms, first_token_ms, usage):
    if not run_id:
        return
    with closing(connect()) as db, db:
        from service.chat.agent_policy import policy_revision
        db.execute('INSERT OR IGNORE INTO requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (
            identity, run_id, kind, provider, model, status, duration_ms, first_token_ms,
            *[usage.get(key) for key in ('input_tokens', 'output_tokens', 'cached_tokens', 'cache_miss_tokens')], policy_revision()))


def summary(run_id):
    with closing(connect()) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute('SELECT * FROM requests WHERE run_id=?', (run_id,))]
    keys = ('input_tokens', 'output_tokens', 'cached_tokens', 'cache_miss_tokens')
    totals = {key: sum(row[key] for row in rows if row[key] is not None) if any(row[key] is not None for row in rows) else None for key in keys}
    measured = [r for r in rows if r['cached_tokens'] is not None and r['input_tokens'] is not None]
    denominator = sum(r['input_tokens'] for r in measured)
    return {**totals, 'requests': len(rows), 'summary_requests': sum(r['kind'] == 'summary' for r in rows),
            'failed_requests': sum(r['status'] != 'completed' for r in rows),
            'duration_ms': sum(r['duration_ms'] for r in rows), 'usage_reported_requests': sum(r['input_tokens'] is not None for r in rows),
            'cache_measured_requests': len(measured),
            'cache_hit_rate': sum(r['cached_tokens'] for r in measured) / denominator if denominator else None,
            'runtime_verification': 'unknown'}


def delete_runs(run_ids):
    with closing(connect()) as db, db:
        db.executemany('DELETE FROM requests WHERE run_id=?', [(value,) for value in run_ids])
