"""Pin normal authoring to its conversation-owned preview or published source."""

import hashlib
from dataclasses import dataclass
from uuid import uuid4

from service.chat import agent_store


@dataclass
class CodeTarget:
    run_id: str
    chat_id: str | None

    def binding(self, project, name):
        from service.chat import ai_chat
        from service.tools import preview_publish
        saved = agent_store.target(self.run_id, project, name)
        if saved:
            return saved
        url = ai_chat.remembered_preview(self.chat_id) if self.chat_id else ''
        source = {'source': 'published', 'url': ''}
        if url:
            owner_project, owner_name, _ = preview_publish.resolve(self.chat_id, url)
            if (owner_project, owner_name) == (project, name):
                source = {'source': 'preview', 'url': url}
        agent_store.bind_target(self.run_id, project, name, source)
        return source

    def execute(self, operation, args):
        from service.chat import ai_chat
        from service.tools import preview_publish, preview_service, tool_activity
        from service.tools.tool_runtime import validate_tool_entrypoint
        project, name = args['project'], args['name']
        ai_chat.tool_path(project, name)
        binding = self.binding(project, name)
        if binding['source'] == 'published':
            return None  # Existing service enforces published revisions and side effects.
        owner_project, owner_name, key = preview_publish.resolve(self.chat_id, binding['url'])
        if (owner_project, owner_name) != (project, name):
            raise ValueError('Preview identity changed')
        path = preview_service.get_preview_file(key)
        content_bytes = path.read_bytes()
        revision = hashlib.sha256(content_bytes).hexdigest()
        if operation == 'read_tool':
            return {'content': content_bytes.decode('utf-8'), 'revision': revision, 'source': 'preview'}
        content = args.get('content', '')
        validate_tool_entrypoint(content)
        if operation == 'validate_tool':
            return {'validated': True, 'executed': False, 'revision': revision, 'source': 'preview'}
        if tool_activity.is_tool_running(project, name):
            raise tool_activity.ToolBusyError()
        if args.get('revision') != revision:
            return {'error': 'Preview revision changed or missing; read current source before saving', 'revision': revision, 'source': 'preview'}
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError('Invalid preview path')
        temporary = path.with_suffix(f'.{uuid4().hex}.tmp')
        try:
            temporary.write_text(content, encoding='utf-8')
            # Recheck immediately before replacing; never publish a preview implicitly.
            if hashlib.sha256(path.read_bytes()).hexdigest() != revision:
                raise ValueError('Preview changed during save')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return {'success': True, 'source': 'preview', 'revision': hashlib.sha256(content.encode()).hexdigest(),
                'requires_manual_run': True, 'executed': False, 'runtime_verified': False,
                'preview_url': binding['url'], 'url': binding['url']}
