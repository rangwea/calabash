"""Desktop language preference and source-key translations."""

import json
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from core.local_paths import app_dir

LANGUAGES = {"zh-CN": "简体中文", "en": "English"}


def language():
    try:
        value = json.loads((app_dir() / "language.json").read_text())["language"]
        return value if value in LANGUAGES else "zh-CN"
    except (OSError, ValueError, KeyError, TypeError):
        return "zh-CN"


def set_language(value):
    if value not in LANGUAGES:
        raise ValueError("Unsupported language")
    app_dir().mkdir(parents=True, exist_ok=True)
    path = app_dir() / "language.json"
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps({"language": value}), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@lru_cache(maxsize=1)
def _english():
    return json.loads((Path(__file__).parent / "locales" / "en.json").read_text(encoding="utf-8"))


def translate(source, target_language, /, **values):
    """Translate without changing the global preference (e.g. bilingual catalogs)."""
    if target_language not in LANGUAGES:
        raise ValueError("Unsupported language")
    translated = _english().get(source, source) if target_language == "en" else source
    return translated.format(**values) if values else translated


def t(source, **values):
    return translate(source, language(), **values)
