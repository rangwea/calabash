import unittest

import main as development
from backend import desktop_server
from core.workspace_app import create_workspace_app


class AppRoutesTests(unittest.TestCase):
    def test_vue_host_and_current_workspace_routes(self):
        app = create_workspace_app()
        paths = {route.path for route in app.routes}
        self.assertIn('/api/workspace/chats', paths)
        self.assertIn('/api/workspace/tools/{project}/{name}/publish', paths)
        self.assertIn('/preview/{project}/{name}', paths)
        self.assertFalse(any(path.startswith(('/user/', '/client/', '/_nicegui')) for path in paths))

    def test_development_and_packaged_backend_share_entrypoint(self):
        self.assertIs(development.main, desktop_server.main)
