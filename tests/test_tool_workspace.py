import asyncio
import unittest
from unittest.mock import AsyncMock, patch

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

    async def test_resume_restores_last_tool_without_recreating_frames(self):
        with patch.object(core, 'loop', asyncio.get_running_loop()):
            workspace = self.workspace()
            workspace.open(self.tool)
            workspace.open({'project': 'demo', 'name': 'two'})
            frames = {key: item[1] for key, item in workspace.items.items()}
            sources = {key: frame._props['src'] for key, frame in frames.items()}
            workspace.hide()
            self.assertFalse(workspace.bar.visible)
            self.assertFalse(workspace.pages.visible)
            self.assertEqual(('demo', 'two'), workspace.active)
            workspace.render_tabs()  # Background updates must not reveal the tab bar.
            self.assertFalse(workspace.bar.visible)
            await workspace.request_resume()
            self.assertTrue(workspace.bar.visible)
            self.assertTrue(workspace.pages.visible)
            self.assertEqual(('demo', 'two'), workspace.active)
            for key, frame in frames.items():
                self.assertIs(frame, workspace.items[key][1])
                self.assertEqual(sources[key], frame._props['src'])
            workspace.dispose()

    async def test_background_closes_do_not_navigate_away_from_current_page(self):
        with patch.object(core, 'loop', asyncio.get_running_loop()):
            changed = []
            with self.container:
                workspace = ToolWorkspace(lambda: self.calls.append('tool'), lambda: self.calls.append('list'), on_change=lambda: changed.append(len(workspace.items)))
            workspace.open(self.tool)
            workspace.open({'project': 'demo', 'name': 'two'})
            workspace.hide()
            self.calls.clear()
            await workspace.close(('demo', 'two'))
            self.assertEqual(('demo', 'one'), workspace.active)
            self.assertFalse(workspace.bar.visible)
            await workspace.close(('demo', 'one'))
            self.assertFalse(workspace.bar.visible)
            await workspace.request_resume()
            self.assertEqual([], self.calls)
            self.assertEqual([1, 0], changed)
            workspace.dispose()

    async def test_declining_navigation_preserves_current_workspace(self):
        async def decline():
            return False

        with patch.object(core, 'loop', asyncio.get_running_loop()):
            with self.container:
                workspace = ToolWorkspace(lambda: self.calls.append('tool'), lambda: self.calls.append('list'), before_navigate=decline)
            workspace.open(self.tool)
            workspace.open({'project': 'demo', 'name': 'two'})
            self.calls.clear()
            await workspace.request_activate(('demo', 'one'))
            self.assertEqual(('demo', 'two'), workspace.active)
            self.assertEqual([], self.calls)
            workspace.hide()
            await workspace.request_resume()
            self.assertFalse(workspace.bar.visible)
            self.assertFalse(workspace.pages.visible)
            self.assertEqual([], self.calls)
            workspace.dispose()

    async def test_edit_targets_current_tool_without_reloading_any_page(self):
        with patch.object(core, 'loop', asyncio.get_running_loop()):
            edit = AsyncMock()
            with self.container:
                workspace = ToolWorkspace(lambda: None, lambda: None, on_edit=edit)
            workspace.open(self.tool)
            workspace.open({'project': 'demo', 'name': 'two', 'title': 'Second tool'})
            frame = workspace.items[('demo', 'two')][1]
            source = frame._props['src']
            await workspace.edit_active()
            edit.assert_awaited_once_with({'project': 'demo', 'name': 'two', 'title': 'Second tool'})
            self.assertIs(frame, workspace.items[('demo', 'two')][1])
            self.assertEqual(source, frame._props['src'])
            workspace.dispose()

    async def test_source_updates_only_apply_after_confirmed_manual_refresh(self):
        with patch.object(core, 'loop', asyncio.get_running_loop()):
            workspace = self.workspace()
            tool = {**self.tool, 'revision': 'first'}
            key = ('demo', 'one')
            workspace.open(tool)
            frame = workspace.items[key][1]
            original_source = frame._props['src']
            workspace.hide()
            workspace.update_tools([{**tool, 'revision': 'updated'}])
            self.assertFalse(workspace.bar.visible)
            self.assertEqual(original_source, frame._props['src'])
            self.assertEqual('first', workspace.revisions[key])
            await workspace.request_resume()
            with patch('service.tools.tool_service.get_tool_by_name', return_value={**tool, 'revision': 'updated'}):
                for confirm in (False, True):
                    task = asyncio.create_task(workspace.refresh_active())
                    for _ in range(5):
                        await asyncio.sleep(0)
                    dialog = [e for e in workspace.client.elements.values() if isinstance(e, ui.dialog)][-1]
                    dialog.submit(confirm)
                    await task
                    self.assertIs(frame, workspace.items[key][1])
                    if confirm:
                        self.assertNotEqual(original_source, frame._props['src'])
                        self.assertEqual('updated', workspace.revisions[key])
                    else:
                        self.assertEqual(original_source, frame._props['src'])
            workspace.dispose()

    async def test_refresh_rechecks_running_jobs_after_confirmation(self):
        with patch.object(core, 'loop', asyncio.get_running_loop()):
            workspace = self.workspace()
            workspace.open(self.tool)
            frame = workspace.items[('demo', 'one')][1]
            source = frame._props['src']
            with patch.object(tool_activity, 'is_tool_running', side_effect=[False, True]), patch.object(ui, 'notify') as notify:
                task = asyncio.create_task(workspace.refresh_active())
                for _ in range(5):
                    await asyncio.sleep(0)
                dialog = [e for e in workspace.client.elements.values() if isinstance(e, ui.dialog)][-1]
                dialog.submit(True)
                await task
                notify.assert_called_once()
            self.assertEqual(source, frame._props['src'])
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
