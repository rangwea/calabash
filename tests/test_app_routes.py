import unittest
from unittest.mock import patch

from nicegui import app

import main as development
import ui.pages  # noqa: F401
from backend import desktop_server
from core import app_factory
from service.tools.preview_service import get_fixed_preview_url, get_preview_url


class AppRoutesTests(unittest.TestCase):
    def test_desktop_pages_have_only_current_routes(self):
        paths = {route.path for route in app.routes}
        for path in (
            "/",
            "/tools/{project_name}/{tool_name}",
            "/preview/{token}",
            "/preview/{username}/{tool_name}",
        ):
            self.assertIn(path, paths)
        self.assertFalse(any(path.startswith(("/user/", "/client/")) for path in paths))

    def test_preview_links_target_current_pages(self):
        self.assertEqual("/preview/example", get_preview_url("example"))
        self.assertEqual(
            "/preview/demo/example", get_fixed_preview_url("demo", "example")
        )

    def test_development_and_desktop_share_startup(self):
        self.assertIs(development.main, desktop_server.main)

    def test_factory_initializes_nicegui_after_registering_pages(self):
        with (
            patch.object(app_factory, "apply_app_styles"),
            patch.object(app_factory, "start_tool_index_watcher"),
            patch("service.files.conversation_files.cleanup_uploads"),
            patch("service.capabilities.capability_packs.recover_existing"),
            patch.object(app_factory.ui, "run_with") as mount,
        ):
            application = app_factory.create_app()
        self.assertIs(mount.call_args.args[0], application)
        self.assertEqual("/", mount.call_args.kwargs["mount_path"])
