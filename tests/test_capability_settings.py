import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from component import capability_settings as settings
from service.capabilities.capability_manifest import PackError


class CapabilitySettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = Mock(configured=True, root=Path("/tmp/plugins"))
        self.controls = settings.CapabilitySettings(self.manager)
        self.controls.render()
        self.controls.confirm = AsyncMock(return_value=True)

    async def test_import_runs_in_worker_and_reports_result(self):
        with patch.object(settings, "choose_path", AsyncMock(return_value="/tmp/plugin.zip")) as choose, patch.object(
            settings.run, "io_bound", AsyncMock(return_value={"id": "media.ffmpeg", "version": "1.0.0", "state": "ready"})
        ) as worker:
            await self.controls.select()
        choose.assert_awaited_once_with(filters=[{"name": "ZIP", "extensions": ["zip"]}])
        worker.assert_awaited_once_with(self.manager.import_zip, "/tmp/plugin.zip")
        self.assertIn("1.0.0", self.controls.message.text)
        self.assertFalse(self.controls.busy)
        self.assertTrue(self.controls.button.enabled)
        self.assertFalse(self.controls.progress.visible)

    async def test_cancel_selection_confirmation_and_wrong_extension(self):
        for path in (None, "/tmp/file.txt", "/tmp/plugin.zip"):
            self.controls.confirm.return_value = False
            with patch.object(settings, "choose_path", AsyncMock(return_value=path)), patch.object(
                settings.run, "io_bound", AsyncMock()
            ) as worker:
                await self.controls.select()
                worker.assert_not_called()
                self.assertFalse(self.controls.busy)

    async def test_unconfigured_does_not_choose_or_import(self):
        self.manager.configured = False
        with patch.object(settings, "choose_path", AsyncMock()) as choose:
            await self.controls.select()
        choose.assert_not_called()
        self.manager.import_zip.assert_not_called()

    async def test_failure_is_friendly_and_restores_controls(self):
        with patch.object(settings, "choose_path", AsyncMock(return_value="/tmp/plugin.zip")), patch.object(
            settings.run, "io_bound", AsyncMock(side_effect=PackError("signature_invalid"))
        ):
            await self.controls.select()
        self.assertEqual(settings.import_error(PackError("signature_invalid")), self.controls.message.text)
        self.assertFalse(self.controls.busy)
        self.assertTrue(self.controls.button.enabled)

    async def test_busy_does_not_open_another_picker(self):
        self.controls.busy = True
        with patch.object(settings, "choose_path", AsyncMock()) as choose:
            await self.controls.select()
        choose.assert_not_called()
