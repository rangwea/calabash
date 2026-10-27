import asyncio
import unittest
from unittest.mock import patch

from nicegui import core, ui

from component.tool_workspace import ToolWorkspace
from service.tools import tool_activity


class ToolWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.container = ui.column()
        self.calls = []
        self.tool = {'project': 'demo', 'name': 'one', 'title': 'First tool'}

    def workspace(self):
        with self.container:
            return ToolWorkspace(lambda: self.calls.append('tool'), lambda: self.calls.append('list'))

    async def test_switch_hide_and_repeat_open_keep_identical_frames(self):
        with patch.object(core, 'loop', asyncio.get_running_loop()):
            workspace = self.workspace()
            workspace.open(self.tool)
            first = workspace.items[('demo', 'one')][1]
            workspace.open({'project': 'demo', 'name': 'two'})
            second = workspace.items[('demo', 'two')][1]
            self.assertFalse(first.visible)
            self.assertTrue(second.visible)
            workspace.hide()
            workspace.open(self.tool)
            self.assertIs(first, workspace.items[('demo', 'one')][1])
            self.assertEqual(2, len(workspace.items))
            self.assertTrue(first.visible)
            self.assertFalse(second.visible)
            self.assertIn('embedded=true', first._props['src'])
            await workspace.close(('demo', 'two'))
            self.assertFalse(first.is_deleted)
            await workspace.close(('demo', 'one'))
            self.assertEqual('list', self.calls[-1])
            workspace.dispose()

    async def test_running_close_wait_or_safe_cancel_preserves_active_file(self):
        class Job:
            owner = 'tool:demo/one'
            tool_owner = None
            cancelled = False

            def cancel(self):
                self.cancelled = True

        with patch.object(core, 'loop', asyncio.get_running_loop()), patch.object(tool_activity, '_publish'), patch.object(tool_activity, '_directory', return_value=None):
            workspace = self.workspace()
            workspace.open(self.tool)
            frame = workspace.items[('demo', 'one')][1]
            job = Job()
            tool_activity.acquire(job)
            try:
                for accept in (False, True):
                    with self.container:
                        closing = asyncio.create_task(workspace.close(('demo', 'one')))
                    for _ in range(5):
                        await asyncio.sleep(0)
                    dialog = [e for e in workspace.client.elements.values() if isinstance(e, ui.dialog)][-1]
                    dialog.submit(accept)
                    await closing
                    self.assertFalse(frame.is_deleted)
                    self.assertEqual(accept, job.cancelled)
                with self.assertRaises(tool_activity.ToolBusyError):
                    tool_activity.acquire(Job())
                workspace.check_jobs()
                self.assertFalse(frame.is_deleted)
            finally:
                tool_activity.release(job)
            workspace.check_jobs()
            self.assertTrue(frame.is_deleted)
            self.assertEqual('list', self.calls[-1])
            self.assertNotIn('tool:demo/one', tool_activity._stopping_tools)
            workspace.dispose()
