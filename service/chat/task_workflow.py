"""Bounded handoff notes and source permissions; no delegation or extra model calls."""
import json
import threading
from uuid import uuid4

from core.local_paths import app_dir
from service.tools.tool_bundles import identity

_lock = threading.RLock()
WRITE_TOOLS = {'write_tool', 'write_tool_file', 'patch_tool_file'}
READ_TOOLS = {'list_tools', 'read_tool', 'read_tool_file', 'search_code', 'read_ui_reference', 'read_ui_preset',
              'read_component_api', 'read_api_contract', 'read_build_diagnostics', 'list_attachments', 'read_attachment', 'read_task_context', 'read_tool_template'}
VERIFY_TOOLS = {'validate_tool', 'check_tool_build', 'inspect_preview', 'verify_preview', 'interact_preview', 'read_tool_logs'}
ROLES = {'main', 'analysis', 'implementation', 'repair', 'verification'}


def allowed(role, name):
    if role not in ROLES:
        raise ValueError('Unknown authoring role')
    if role in {'main', 'implementation', 'repair'}:
        return True
    return name in READ_TOOLS or name in (VERIFY_TOOLS if role == 'verification' else {'set_task_brief'})


class TaskWorkflow:
    def __init__(self, chat_id, run_id, role='main'):
        if chat_id is not None:
            identity(chat_id)
        identity(run_id)
        if role not in ROLES:
            raise ValueError('Unknown authoring role')
        self.path = app_dir() / 'agent/task_contexts' / (chat_id + '.json') if chat_id else None
        for part in (self.path, *self.path.parents) if self.path else ():
            if part.is_symlink():
                raise ValueError('Symlink task contexts are forbidden')
            if part == app_dir():
                break
        try:
            old = json.loads(self.path.read_text()) if self.path and self.path.is_file() and self.path.stat().st_size < 32768 else {}
        except (OSError, ValueError):
            old = {}
        if not isinstance(old, dict):
            old = {}
        self.repairing = role == 'repair'
        self.role = role
        self.data = {'version': 1, 'run': run_id, 'phase': 'analysis', 'brief': old.get('brief', {}),
                     'tool': old.get('tool'), 'checks': None, 'runtime_verified': False}
        self.persist()

    def public(self):
        return {**self.data, 'role': self.role, 'source_write_allowed': self.role in {'main', 'implementation', 'repair'},
                'permissions': {'publish': False, 'business_actions': 'user_confirmation_required', 'one_writer_per_conversation': True}}

    def persist(self):
        if self.path is None:
            return
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name('.' + uuid4().hex)
            try:
                temporary.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
                temporary.chmod(0o600)
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)

    def brief(self, goal, requirements, preserve, acceptance, redact):
        if not isinstance(goal, str) or len(goal) > 500:
            raise ValueError('Invalid task goal')
        value = {'goal': redact(goal)}
        for key, items in [('requirements', requirements), ('preserve', preserve), ('acceptance', acceptance)]:
            if len(items) > 12 or any(not isinstance(item, str) or len(item) > 300 for item in items):
                raise ValueError('Task notes must be short and bounded')
            value[key] = [redact(item) for item in items]
        self.data['brief'] = value
        self.persist()
        return self.public()

    def observe(self, name, args, output):
        if name in {'read_task_context', 'set_task_brief'}:
            return
        try:
            result = json.loads(output) if isinstance(output, str) else {}
        except (ValueError, TypeError):
            result = {}
        if not isinstance(result, dict) or result.get('error'):
            return
        if name == 'read_tool_logs' or name == 'read_build_diagnostics' and result.get('state') == 'failed':
            self.repairing = True
        if name in WRITE_TOOLS:
            self.data['phase'] = 'repair' if self.repairing else 'implementation'
            self.data['checks'] = None
        elif name in VERIFY_TOOLS:
            self.data['phase'] = 'verification'
        if args.get('project') and args.get('name'):
            self.data['tool'] = {'project': identity(args['project']), 'name': identity(args['name']), 'revision': result.get('revision', args.get('revision', ''))}
        if name == 'check_tool_build':
            self.data['checks'] = {'revision': result.get('revision'), 'build': result.get('state')}
        self.persist()

    def finish(self, succeeded):
        self.data['phase'] = 'manual_review' if succeeded else 'paused'
        self.persist()


def delete_context(chat_id, storage_root=None):
    identity(chat_id)
    root = storage_root or app_dir()
    path = root / 'agent/task_contexts' / (chat_id + '.json')
    for part in (path.parent, *path.parent.parents):
        if part.is_symlink():
            raise ValueError('Symlink task contexts are forbidden')
        if part == root:
            break
    path.unlink(missing_ok=True)
