import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nicegui import core, ui

from component.tool_results import ToolResults
from service.chat import ai_chat
from service.files import tool_outputs


class OutputHistoryUITests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_results_take_no_space_and_new_outputs_can_expand(self):
        outputs = tool_outputs.ToolOutputs(owner=("tool:demo/compact-ui", None))
        with patch.object(core, "loop", asyncio.get_running_loop()), self.container:
            results = ToolResults(outputs)
            self.assertFalse(results.container.visible)
            self.assertEqual([], list(results.container.descendants()))
            outputs.write("report.txt", lambda path: path.write_text("synthetic"))
            results.refresh()
            self.assertTrue(results.container.visible)
            self.assertFalse(results.body.visible)
            results.toggle()
            self.assertTrue(results.body.visible)
            results.refresh()
            self.assertTrue(results.body.visible)
            results.toggle()
            self.assertFalse(results.body.visible)

    def setUp(self):
        self.container = ui.column()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for module in (ai_chat, tool_outputs):
            patcher = patch.object(module, "app_dir", return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_implicit_scope_restore_pagination_and_unavailable_actions(self):
        owner = ("tool:demo/history-ui", None)
        writer = tool_outputs.ToolOutputs(owner=owner)
        for index in range(22):
            writer.write(f"report-{index}.txt", lambda path: path.write_text("sample"))
        file_id = writer.files()[0]["id"]
        writer.path(file_id).unlink()
        with patch.object(core, "loop", asyncio.get_running_loop()), self.container, patch.object(ui.context.client, "calabash_output_owner", owner, create=True):
            restored = ToolResults()
            self.assertEqual(owner, restored.outputs.owner)
            self.assertEqual(22, len(restored.outputs.files()))
            buttons = [element for element in restored.container.descendants() if isinstance(element, ui.button)]
            self.assertEqual(3, len([button for button in buttons if not button.enabled]))
            self.assertEqual(20, len([button for button in buttons if button._props.get("icon") == "download"]))
            restored.show_more()
            buttons = [element for element in restored.container.descendants() if isinstance(element, ui.button)]
            self.assertEqual(22, len([button for button in buttons if button._props.get("icon") == "download"]))
            self.assertFalse(any(button._props.get("icon") == "expand_more" for button in buttons))

    async def test_native_save_cancel_error_and_retry_keep_result_available(self):
        outputs = tool_outputs.ToolOutputs(owner=("tool:demo/save-ui", None))
        file_id = outputs.write("report.txt", lambda path: path.write_text("synthetic"))
        with patch.object(core, "loop", asyncio.get_running_loop()), self.container:
            results = ToolResults(outputs)
            from unittest.mock import AsyncMock

            with patch.object(outputs, "save_ticket", return_value="a" * 32), patch.object(ui, "run_javascript", AsyncMock(side_effect=[{}, {"error": True}, {}])), patch.object(ui, "notify") as notify:
                await results.download(file_id)
                notify.assert_not_called()
                await results.download(file_id)
                self.assertEqual(1, notify.call_count)
                await results.download(file_id)
                self.assertEqual(1, notify.call_count)
            self.assertEqual("synthetic", outputs.path(file_id).read_text())
            self.assertTrue(outputs.files()[0]["available"])
