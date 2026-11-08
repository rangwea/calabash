"""One bundled starter, returned as source data without filesystem mutation."""
import json
from pathlib import Path

from service.tools.tool_bundles import identity


def base_template(project: str, name: str) -> dict[str, str]:
    project, name = identity(project), identity(name)
    root = Path(__file__).resolve().parents[2] / 'agent/skills/calabash/templates/base'
    files = {path: (root / path).read_text(encoding='utf-8') for path in
             ('tool.json', 'frontend/App.vue', 'backend/main.py')}
    manifest = json.loads(files['tool.json'])
    manifest.update(project=project, name=name)
    files['tool.json'] = json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'
    return files
