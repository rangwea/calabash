"""Bounded browser diagnostics sanitization, independent of UI framework."""

import re


def redact(value, secrets=()):
    from service.chat import model_providers
    text = str(value)[:20000]
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            text = text.replace(secret, '[CREDENTIAL REDACTED]')
    for connection in model_providers.load().get('connections', {}).values():
        key = connection.get('key')
        if isinstance(key, str) and key:
            text = text.replace(key, '[CREDENTIAL REDACTED]')
    text = re.sub(r'([?&][A-Za-z0-9_.-]+=)[^\s&#)]+', r'\1[REDACTED]', text)
    return re.sub(r'(?i)(bearer\s+|(?:api[_-]?key|password|secret|token|authorization)\s*[:=]\s*)[^\s,;"}]+', r'\1[CREDENTIAL REDACTED]', text)


def clean_page(result, secrets=()):
    data = {}
    for key in ('text', 'error'):
        if isinstance(result.get(key), str):
            data[key] = redact(result[key], secrets)[:1600]
    data['horizontal_overflow'] = result.get('horizontal_overflow') if type(result.get('horizontal_overflow')) is bool else None
    for key, fields in {
        'elements': {'id', 'tag', 'role', 'label', 'enabled', 'input_type', 'editable'},
        'media': {'id', 'paused', 'ended', 'current_time', 'duration', 'ready_state', 'network_state', 'error_code', 'source', 'muted'},
    }.items():
        values = result.get(key, [])
        data[key] = [{k: redact(v, secrets)[:160] if isinstance(v, str) else v for k, v in item.items() if k in fields and isinstance(v, (str, int, float, bool, type(None)))} for item in values[:100] if isinstance(item, dict)] if isinstance(values, list) else []
    return data
