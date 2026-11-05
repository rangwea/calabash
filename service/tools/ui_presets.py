"""Built-in, versioned design packs. Settings never alter existing tools."""
import json
import re
from pathlib import Path
from uuid import uuid4

from core.local_paths import app_dir

ROOT = Path(__file__).resolve().parents[2] / 'agent/skills/calabash/references/ui-presets'


def catalog():
    return [json.loads(path.read_text(encoding='utf-8')) for path in sorted(ROOT.glob('*/preset.json'))]


def get(identity):
    for value in catalog():
        aliases = [value['id'], value['title'], value['mention'], *value.get('aliases', [])]
        if isinstance(identity, str) and identity.casefold() in [alias.casefold() for alias in aliases]:
            return value
    raise ValueError('Unknown UI preset')


def default():
    path = app_dir() / 'ui_preferences.json'
    try:
        return get(json.loads(path.read_text())['default'])['id']
    except (OSError, ValueError, KeyError, TypeError):
        return 'office'


def set_default(identity):
    identity = get(identity)['id']
    path = app_dir() / 'ui_preferences.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.ui-' + uuid4().hex)
    try:
        temporary.write_text(json.dumps({'default': identity}), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def requested(messages):
    latest = next((m.get('content', '') for m in reversed(messages) if m.get('role') == 'user'), '')
    if not isinstance(latest, str):
        return None
    matches = []
    for preset in catalog():
        for alias in [preset['id'], preset['title'], preset['mention'], *preset.get('aliases', [])]:
            for match in re.finditer(r'(?<!\S)@(?:ui:)?' + re.escape(alias) + r'(?=\s|$|[，。,:：])', latest, re.IGNORECASE):
                matches.append((match.start(), preset['id']))
    return max(matches)[1] if matches else None


def apply(files, messages, existing=None):
    """Authoritative explicit > current snapshot > default selection."""
    files = dict(files)
    meta = json.loads(files['tool.json'])
    old = json.loads(existing['tool.json']) if existing else {}
    explicit = requested(messages)
    current = old.get('ui')
    if existing and not explicit and not current:
        meta.pop('ui', None)
        files['tool.json'] = json.dumps(meta, ensure_ascii=False)
        if 'frontend/calabash-theme.css' in existing:
            files['frontend/calabash-theme.css'] = existing['frontend/calabash-theme.css']
        else:
            files.pop('frontend/calabash-theme.css', None)
        return files
    if not explicit and current and existing.get('frontend/calabash-theme.css'):
        meta['ui'] = current
        files['tool.json'] = json.dumps(meta, ensure_ascii=False)
        files['frontend/calabash-theme.css'] = existing['frontend/calabash-theme.css']
        return files
    preset = get(explicit or (current or {}).get('preset') or default())
    meta['ui'] = {'preset': preset['id'], 'version': preset['version']}
    files['tool.json'] = json.dumps(meta, ensure_ascii=False)
    theme = 'frontend/calabash-theme.css'
    if explicit or not existing:
        files[theme] = (ROOT / preset['id'] / 'tokens.css').read_text(encoding='utf-8')
    elif theme in existing:
        files[theme] = existing[theme]
    else:
        files[theme] = (ROOT / preset['id'] / 'tokens.css').read_text(encoding='utf-8')
    return files


def reference(identity):
    preset = get(identity)
    identity = preset['id']
    return {**preset, 'rules': (ROOT / identity / 'guide.md').read_text(encoding='utf-8'),
            'tokens': (ROOT / identity / 'tokens.css').read_text(encoding='utf-8'),
            'example': (ROOT / identity / 'example.vue').read_text(encoding='utf-8')}
