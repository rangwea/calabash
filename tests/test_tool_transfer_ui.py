import asyncio
import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, patch

from nicegui import ui

from component import tool_transfer as transfer
from service.tools.tool_archives import ToolArchiveError, ToolPackage

PACKAGE = ToolPackage(
    "demo", "example", b"def main(): pass", "Example", "Description", "media.ffmpeg"
)


class ToolTransferUITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.changed = Mock()
        self.controls = transfer.ToolTransfer(self.changed)
        self.controls.render()
        self.addCleanup(self.controls.container.delete)
        self.translation = patch.object(
            transfer, "t", side_effect=lambda text, **values: text.format(**values)
        )
        self.translation.start()
        self.addCleanup(self.translation.stop)

    async def show_dialog(self):
        client = self.controls.container.client
        existing = set(client.elements)
        task = asyncio.create_task(self.controls.confirm(PACKAGE))
        await asyncio.sleep(0)
        if task.done():
            await task
        dialog = next(
            element
            for element in client.elements.values()
            if isinstance(element, ui.dialog) and element.id not in existing
        )
        return task, dialog

    def controls_in(self, dialog):
        elements = list(dialog.descendants())
        name = next(
            element
            for element in elements
            if isinstance(element, ui.input)
            and element._props.get("label") == "工具标识"
        )
        overwrite = next(
            element for element in elements if isinstance(element, ui.checkbox)
        )
        accept = next(
            element
            for element in elements
            if isinstance(element, ui.button)
            and element._props.get("label") == "确认导入"
        )
        return name, overwrite, accept

    async def test_cancel_dialog_never_installs(self):
        with (
            patch.object(transfer.archives, "target_revision", return_value=None),
            patch.object(transfer.archives, "install") as install,
        ):
            task, dialog = await self.show_dialog()
            dialog.submit(False)
            self.assertFalse(await task)
            install.assert_not_called()
            self.changed.assert_not_called()

    async def test_existing_tool_requires_checkbox_or_new_name(self):
        with (
            patch.object(
                transfer.archives,
                "target_revision",
                side_effect=lambda project, name: (
                    "revision" if name == "example" else None
                ),
            ),
            patch.object(transfer.archives, "install") as install,
        ):
            task, dialog = await self.show_dialog()
            name, overwrite, accept = self.controls_in(dialog)
            self.assertFalse(accept.enabled)
            self.assertTrue(overwrite.visible)
            overwrite.set_value(True)
            self.assertTrue(accept.enabled)
            name.set_value("renamed")
            self.assertFalse(overwrite.value)
            self.assertFalse(overwrite.visible)
            self.assertTrue(accept.enabled)
            next(iter(accept._event_listeners.values())).handler(None)
            self.assertTrue(await task)
            install.assert_called_once_with(
                PACKAGE, "demo", "renamed", expected_revision=None
            )

    async def test_dialog_survives_tool_list_refresh(self):
        with patch.object(transfer.archives, "target_revision", return_value=None):
            task, dialog = await self.show_dialog()
            self.controls.container.clear()
            self.assertFalse(dialog.is_deleted)
            dialog.submit(False)
            self.assertFalse(await task)

    async def test_changed_destination_requires_new_approval(self):
        with (
            patch.object(
                transfer.archives, "target_revision", side_effect=["old", "new"]
            ),
            patch.object(
                transfer.archives,
                "install",
                side_effect=[ToolArchiveError("changed"), {}],
            ) as install,
        ):
            task, dialog = await self.show_dialog()
            _, overwrite, accept = self.controls_in(dialog)
            overwrite.set_value(True)
            next(iter(accept._event_listeners.values())).handler(None)
            self.assertFalse(task.done())
            self.assertFalse(overwrite.value)
            self.assertFalse(accept.enabled)
            overwrite.set_value(True)
            next(iter(accept._event_listeners.values())).handler(None)
            self.assertTrue(await task)
            self.assertEqual("new", install.call_args.kwargs["expected_revision"])

    async def test_picker_cancellation_and_failed_inspection_restore_button(self):
        for chosen, failure in [
            (None, None),
            ("/tmp/tool.zip", ToolArchiveError("format")),
        ]:
            with (
                patch.object(transfer, "choose_path", AsyncMock(return_value=chosen)),
                patch.object(
                    transfer.run, "io_bound", AsyncMock(side_effect=failure)
                ) as inspect,
                patch.object(self.controls, "confirm", AsyncMock()) as confirm,
                patch.object(transfer.ui, "notify"),
            ):
                await self.controls.select()
                if not chosen:
                    inspect.assert_not_called()
                confirm.assert_not_called()
                self.assertTrue(self.controls.button.enabled)
                self.assertFalse(self.controls.busy)
                self.changed.assert_not_called()

    async def test_success_refreshes_only_after_confirmation_and_controls_restore(self):
        with (
            patch.object(
                transfer, "choose_path", AsyncMock(return_value="/tmp/tool.zip")
            ),
            patch.object(transfer.run, "io_bound", AsyncMock(return_value=PACKAGE)),
            patch.object(self.controls, "confirm", AsyncMock(return_value=True)),
            patch.object(transfer.ui, "notify"),
        ):
            self.changed.side_effect = lambda: self.assertTrue(
                self.controls.button.enabled
            )
            await self.controls.select()
            self.changed.assert_called_once()

    async def test_browser_export_downloads_zip_without_native_ticket(self):
        @contextmanager
        def delivery(*_):
            yield b"zip data", None

        with (
            patch.object(transfer.archives, "export_delivery", delivery),
            patch.object(transfer.ui, "download") as download,
        ):
            await transfer.export_tool({"project": "demo", "name": "example"})
        download.assert_called_once_with(
            b"zip data", filename="example.zip", media_type="application/zip"
        )

    async def test_native_export_uses_existing_save_ticket_bridge_and_cleans_up(self):
        cleaned = Mock()

        @contextmanager
        def delivery(*_):
            try:
                yield b"zip data", "a" * 32
            finally:
                cleaned()

        with (
            patch.object(transfer.archives, "export_delivery", delivery),
            patch.object(
                transfer.ui, "run_javascript", AsyncMock(return_value={})
            ) as bridge,
            patch.object(transfer.ui, "download") as download,
        ):
            await transfer.export_tool({"project": "demo", "name": "example"})
        self.assertIn("save_tool_output", bridge.call_args.args[0])
        download.assert_not_called()
        cleaned.assert_called_once()
