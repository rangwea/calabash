import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nicegui import core, ui

from component.tool_repair import RepairFeedback
from core import i18n
from service.chat import ai_chat, model_providers
from service.tools import tool_repairs


class RepairConsentUITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.container = ui.column()

    async def check_consent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'demo/example.py'
            path.parent.mkdir()
            path.write_text('def main(): pass\n')
            with (
                patch.object(core, 'loop', asyncio.get_running_loop()),
                patch.object(ai_chat, 'app_dir', return_value=root),
                patch.object(ai_chat, 'tools_dir', return_value=root),
                patch.object(i18n, 'app_dir', return_value=root),
                patch.object(model_providers, 'active', return_value=('deepseek', 'synthetic', {'key': 'synthetic', 'base_url': 'https://example.test'})),
                patch.object(model_providers, 'load', return_value={'connections': {}}),
                patch.object(tool_repairs, 'approve') as approve,
                patch('core.tool_run_logs.logs_dir', return_value=root / 'logs'),
                patch('core.tool_run_logs.app_dir', return_value=root),
                patch.object(ui.navigate, 'to'),
            ):
                container = self.container
                initial_ids = set(container.client.elements)
                with container:
                    feedback = RepairFeedback('demo', 'example')
                feedback.capture(ValueError('Synthetic diagnostic detail'))
                async def confirm():
                    with container:
                        await feedback.confirm()
                task = asyncio.create_task(confirm())
                try:
                    for _ in range(8):
                        await asyncio.sleep(0)
                    if task.done():
                        task.result()
                    elements = [e for id_, e in container.client.elements.items() if id_ not in initial_ids]
                    self.assertFalse(any(isinstance(e, ui.checkbox) for e in elements))
                    self.assertTrue(any('Agent' in str(getattr(e, 'text', '')) and ('日志' in str(getattr(e, 'text', '')) or 'logs' in str(getattr(e, 'text', ''))) for e in elements))
                    dialog = next(e for e in elements if isinstance(e, ui.dialog))
                    dialog.submit(True)
                    await task
                    self.assertEqual({}, approve.call_args.kwargs)
                finally:
                    if not task.done():
                        task.cancel()
                    container.delete()

    async def test_confirmation_discloses_tool_log_access(self):
        await self.check_consent()
