"""Read only the bundled UI guidance, never user files or arbitrary paths."""

from pathlib import Path

REFERENCE_ROOT = Path(__file__).resolve().parents[2] / 'agent/skills/calabash/references'
REFERENCES = (
    'design.md', 'design-details.md', 'design-scenes.md',
    'simple-tool.py', 'query-tool.py', 'file-tool.py',
    'office-workspace.py', 'media-workspace.py',
)


def read_reference(name: str) -> dict:
    if not isinstance(name, str) or name not in REFERENCES:
        return {'error': 'Unknown UI reference', 'available': list(REFERENCES)}
    return {'name': name, 'content': (REFERENCE_ROOT / name).read_text(encoding='utf-8'),
            'executed': False, 'kind': 'bundled_ui_reference'}
