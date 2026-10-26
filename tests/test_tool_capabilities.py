import asyncio
import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from nicegui import core, ui

from component.capability_settings import CapabilitySettings
from component.tool_capabilities import ToolCapabilityGate
from ui.pages import preview
from ui.pages import tools
from service.capabilities.capability_packs import official_manager
from service.capabilities.tool_capabilities import (
    CapabilityIssue,
    Requirement,
    ToolCapabilityError,
    check_requirements,
    parse_requirements,
)
from service.tools.tool_runtime import load_tool_entrypoint
from service.tools.tool_service import load_and_execute_project_tool


class RequirementTests(unittest.TestCase):
    def manager(self, state="ready", version="9.0.2"):
        return SimpleNamespace(selfchecks={"media.ffmpeg": Mock()},
                               status=Mock(return_value={"state": state, "version": version}))

    def test_parse_optional_capability_declarations(self):
        self.assertEqual((), parse_requirements("def main(): pass"))
        self.assertEqual((Requirement("media.ffmpeg", "9.0.2"), Requirement("document.ocr")),
                         parse_requirements('"""requires: media.ffmpeg >= 9.0.2, document.ocr"""'))
        self.assertEqual((), parse_requirements('"""requires: """'))

    def test_reject_malformed_duplicate_and_unbounded_declarations(self):
        for value in ("media.ffmpeg,media.ffmpeg", "media.ffmpeg,", "media.ffmpeg==9.0.2",
                      "media.ffmpeg>=9.0", "https://example.test/plugin.zip", "pandas",
                      "media.ffmpeg>=9999999.0.0", "a.b" * 1000):
            with self.subTest(value=value[:50]), self.assertRaises(ToolCapabilityError) as caught:
                parse_requirements(f'"""requires: {value}"""')
            self.assertTrue(caught.exception.invalid)

    def test_check_missing_corrupt_version_and_unsupported(self):
        requirement = (Requirement("media.ffmpeg", "9.0.2"),)
        for state, version, expected in (("not_installed", None, "missing"), ("invalid", None, "damaged"),
                                          ("ready", "9.0.1", "version"), ("ready", "10.0.0", None)):
            with self.subTest(state=state, version=version):
                issues = check_requirements(requirement, self.manager(state, version))
                self.assertEqual([expected] if expected else [], [issue.reason for issue in issues])
        manager = self.manager()
        self.assertEqual("unsupported", check_requirements((Requirement("document.ocr"),), manager)[0].reason)
        self.assertEqual("unsupported", check_requirements((Requirement("custom.engine"),), manager)[0].reason)
        manager.status.assert_not_called()
        manager.status.side_effect = OSError("broken")
        self.assertEqual("damaged", check_requirements(requirement, manager)[0].reason)

    def test_block_before_import_or_top_level_side_effects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "tool.py"
            marker = root / "must-not-exist"
            source.write_text('"""requires: media.ffmpeg>=9.0.2"""\n'
                              f'from pathlib import Path\nPath({str(marker)!r}).touch()\n'
                              'raise RuntimeError("must not import")\ndef main(): pass\n')
            with patch("service.capabilities.tool_capabilities.official_manager", return_value=self.manager("not_installed", None)), self.assertRaises(ToolCapabilityError):
                load_tool_entrypoint("blocked", str(source))
            self.assertFalse(marker.exists())

    def test_retry_rereads_latest_source_and_rechecks(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "tool.py"
            source.write_text('"""requires: media.ffmpeg>=9.0.2"""\ndef main(): return 42\n')
            manager = self.manager("not_installed", None)
            with patch("service.capabilities.tool_capabilities.official_manager", return_value=manager):
                with self.assertRaises(ToolCapabilityError):
                    load_tool_entrypoint("blocked", str(source))
                manager.status.return_value = {"state": "ready", "version": "9.0.2"}
                main, _ = load_tool_entrypoint("ready", str(source))
                self.assertEqual(42, main())
                self.assertEqual(2, manager.status.call_count)

    def test_executes_checked_source_not_a_second_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "tool.py"
            source.write_text("def main(): return 1\n")
            def change(content):
                source.write_text('raise RuntimeError("changed after check")\ndef main(): return 2\n')
            with patch("service.tools.tool_runtime.require_tool_capabilities", side_effect=change):
                main, _ = load_tool_entrypoint("snapshot", str(source))
            self.assertEqual(1, main())

    def test_formal_service_preserves_typed_blocker(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "demo"
            project.mkdir()
            (project / "tool.py").write_text('"""requires: document.ocr"""\ndef main(): pass\n')
            with patch("service.tools.tool_service.tools_dir", return_value=Path(temporary)), self.assertRaises(ToolCapabilityError):
                load_and_execute_project_tool("demo", "tool")


class CapabilityGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        patcher = patch.object(core, "loop", asyncio.get_running_loop())
        patcher.start()
        self.addCleanup(patcher.stop)

    def setUp(self):
        self.requirement = Requirement("media.ffmpeg", "9.0.2")
        self.error = ToolCapabilityError((self.requirement,), (CapabilityIssue(self.requirement, "missing"),))
        self.manager = SimpleNamespace(root=Path("/tmp/plugins"), configured=True,
                                       selfchecks={"media.ffmpeg": Mock()}, status=Mock())
        self.gate = ToolCapabilityGate(self.error, self.manager)
        self.container = ui.column()

    async def test_import_success_rechecks_without_running_or_reloading(self):
        self.manager.status.return_value = {"state": "ready", "version": "9.0.2"}
        with self.container:
            self.gate.render()
        async def worker(function, *args):
            return function(*args)
        with patch("component.tool_capabilities.run.io_bound", worker), patch.object(ui, "run_javascript") as reload:
            await self.gate.imported({"id": "media.ffmpeg"})
            self.assertFalse(self.gate.issues)
            reload.assert_not_called()
            self.gate.retry()
            reload.assert_called_once_with("window.location.reload()")

    async def test_import_of_other_pack_does_not_mark_requirements_ready(self):
        self.manager.status.return_value = {"state": "not_installed", "version": None}
        with self.container:
            self.gate.render()
        with patch("component.tool_capabilities.run.io_bound", AsyncMock(return_value=self.error.issues)), patch.object(ui, "run_javascript") as reload:
            await self.gate.imported({"id": "document.ocr"})
        self.assertEqual("missing", self.gate.issues[0].reason)
        reload.assert_not_called()

    async def test_preview_routes_block_without_calling_tool(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "preview.py"
            path.write_text("def main(): pass")
            with self.container, patch.object(preview, "get_preview_file", return_value=path), patch.object(
                preview, "load_tool_entrypoint", side_effect=self.error
            ), patch.object(preview, "render_capability_gate") as render, patch.object(
                preview, "render_tool_shell", return_value=nullcontext()
            ), patch.object(preview, "_render_error") as generic:
                await preview._render_preview("capability-test", "test", embedded=True)
            render.assert_called_once_with(self.error)
            generic.assert_not_called()

    async def test_formal_route_shows_gate_not_generic_error(self):
        with self.container, patch.object(tools, "load_and_execute_project_tool", side_effect=self.error), patch.object(
            tools, "render_capability_gate"
        ) as render, patch.object(tools, "render_tool_shell", return_value=nullcontext()), patch.object(
            tools, "_render_tool_error"
        ) as generic:
            await tools.tools_handler(None, "demo", "tool")
        render.assert_called_once_with(self.error)
        generic.assert_not_called()


@unittest.skipUnless(os.environ.get("CALABASH_FFMPEG_TEST_ZIP"), "Set CALABASH_FFMPEG_TEST_ZIP to test real ZIP import")
class RealCapabilityPreflightTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.container = ui.column()

    async def test_missing_import_then_manual_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = official_manager()
            manager.root = root / "plugins"
            marker = root / "executed"
            source = root / "tool.py"
            source.write_text('"""requires: media.ffmpeg>=9.0.2"""\nfrom pathlib import Path\n'
                              f'Path({str(marker)!r}).touch()\ndef main(): return 42\n')
            with patch("service.capabilities.tool_capabilities.official_manager", return_value=manager):
                with self.assertRaises(ToolCapabilityError) as caught:
                    load_tool_entrypoint("initial", str(source))
                gate = ToolCapabilityGate(caught.exception, manager)
                controls = CapabilitySettings(manager, on_imported=gate.imported)
                with self.container:
                    gate.render()
                    controls.render()
                controls.confirm = AsyncMock(return_value=True)
                async def worker(function, *args):
                    return await asyncio.to_thread(function, *args)
                with patch.object(core, "loop", asyncio.get_running_loop()), patch(
                    "component.capability_settings.choose_path", AsyncMock(return_value=os.environ["CALABASH_FFMPEG_TEST_ZIP"])
                ), patch("component.capability_settings.run.io_bound", worker), patch.object(ui, "run_javascript") as reload:
                    await controls.select()
                    self.assertFalse(gate.issues)
                    self.assertFalse(marker.exists())
                    reload.assert_not_called()
                    main, _ = load_tool_entrypoint("manual_retry", str(source))
                    self.assertEqual(42, main())
                    self.assertTrue(marker.exists())
