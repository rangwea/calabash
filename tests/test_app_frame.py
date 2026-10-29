"""Native titlebar controls must keep their own inset and clickable actions."""

import unittest
from unittest.mock import patch

from nicegui import ui

from component.app_frame import render_app_frame


class AppFrameTests(unittest.TestCase):
    def test_only_macos_uses_overlay_chrome_and_actions_never_start_dragging(self):
        for system, expected in [('Darwin', True), ('Windows', False), ('Linux', False)]:
            with self.subTest(system=system), patch('component.app_frame.platform.system', return_value=system):
                with ui.column() as container:
                    render_app_frame(action=lambda: None)
                frame = next(element for element in container.descendants() if 'app-window-frame' in element._classes)
                self.assertEqual(expected, 'app-window-frame-macos' in frame._classes)
                self.assertEqual('deep', frame._props['data-tauri-drag-region'])
                button = next(element for element in frame.descendants() if isinstance(element, ui.button))
                self.assertEqual('false', button.parent_slot.parent._props['data-tauri-drag-region'])
                self.assertTrue(button._props['aria-label'])
