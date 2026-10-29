import asyncio
import unittest
from unittest.mock import patch

from nicegui import core, ui

from component.model_settings import (
    ModelDrafts,
    confirm_settings_leave,
    render_model_settings,
    window_drafts,
)
from service.chat import model_providers


class ModelDraftTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.container = ui.column()
        self.client = ui.context.client
        if hasattr(self.client, 'calabash_model_drafts'):
            del self.client.calabash_model_drafts

    async def test_drafts_survive_editor_recreation_without_writing_config(self):
        config = {'connections': {'deepseek': {'key': 'synthetic', 'models': ['sample']}}}
        with patch.object(model_providers, 'load', return_value=config), patch.object(model_providers, 'save') as save:
            with self.container:
                render_model_settings()
            endpoint = next(e for e in self.container.descendants() if isinstance(e, ui.input) and e.label == 'API 地址')
            endpoint.set_value('https://draft.invalid/v1')
            state = window_drafts(self.client)
            self.assertTrue(state.dirty())
            self.container.clear()
            with self.container:
                render_model_settings()
            endpoint = next(e for e in self.container.descendants() if isinstance(e, ui.input) and e.label == 'API 地址')
            self.assertEqual('https://draft.invalid/v1', endpoint.value)
            save.assert_not_called()
            self.assertNotIn('base_url', config['connections']['deepseek'])

    async def test_leave_requires_choice_and_keeps_draft_on_both_choices(self):
        with patch.object(core, 'loop', asyncio.get_running_loop()), patch.object(model_providers, 'load', return_value={'connections': {}}):
            state = window_drafts(self.client)
            state.get('deepseek')['models'] = 'edited'
            for choice in (False, True):
                with self.container:
                    task = asyncio.create_task(confirm_settings_leave(self.client))
                for _ in range(5):
                    await asyncio.sleep(0)
                dialog = next(e for e in reversed(list(self.client.elements.values())) if isinstance(e, ui.dialog))
                dialog.submit(choice)
                self.assertEqual(choice, await task)
                self.assertEqual('edited', state.get('deepseek')['models'])
                self.assertTrue(state.dirty())
            state.busy = True
            self.assertFalse(await confirm_settings_leave(self.client))

    def test_provider_drafts_and_window_states_are_independent(self):
        with patch.object(model_providers, 'load', return_value={'connections': {}}):
            one, two = ModelDrafts(), ModelDrafts()
            one.get('deepseek')['key'] = 'synthetic'
            self.assertEqual('', one.get('openai')['key'])
            self.assertEqual('', two.get('deepseek')['key'])
