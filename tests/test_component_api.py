import tempfile
import ast
import unittest
from pathlib import Path

from service.chat import ai_chat
from service.tools.component_api import diagnose, read_api


class ComponentApiTests(unittest.TestCase):
    def test_tool_host_context_blocks_page_layout_components_before_execution(self):
        from service.tools.tool_runtime import validate_tool_entrypoint, ToolEntryPointError
        for name, component in [('left_drawer', 'LeftDrawer'), ('right_drawer', 'RightDrawer'), ('header', 'Header'), ('footer', 'Footer')]:
            with self.subTest(component=component):
                api = read_api(component)
                self.assertFalse(api['allowed_in_tool'])
                self.assertEqual('Calabash', api['host_context']['page_layout_owner'])
                with self.assertRaisesRegex(ToolEntryPointError, 'requires the page root'):
                    validate_tool_entrypoint(f'from nicegui import ui as gui\ndef main():\n    gui.{name}()\n')
        validate_tool_entrypoint('from nicegui import ui\ndef main():\n    with ui.row():\n        with ui.column():\n            ui.label("Local menu")\n')
        validate_tool_entrypoint('def main(ui):\n    ui.left_drawer()\n')

    def test_media_and_control_components_report_actual_contracts(self):
        for component in ('Audio', 'Video', 'Slider', 'Timer', 'Button'):
            api = read_api(component)
            self.assertNotIn('error', api)
            self.assertIn(component, next(s['function'] for s in ai_chat.schemas() if s['function']['name'] == 'read_component_api')['parameters']['properties']['component']['enum'])
        audio = read_api('Audio')
        self.assertTrue(next(p for p in audio['constructor'] if p['name'] == 'src')['required'])
        for method in ('play', 'pause', 'seek', 'set_source'):
            self.assertFalse(audio['methods'][method]['async'])
            self.assertTrue(audio['methods'][method]['returns_none'])
        self.assertTrue(read_api('Slider')['properties']['value']['writable'])
        self.assertNotIn('get_duration', audio['methods'])
        self.assertNotIn('get_position', audio['methods'])
        self.assertIn('HTMLMediaElement', audio['usage'])

    def test_media_static_checks_cover_nested_callbacks_and_respect_shadowing(self):
        from core.tool_api_contracts import api_errors
        source = '''from nicegui import ui as gui
def main():
    audio = gui.audio().classes('hidden')
    async def play():
        await audio.play()
        await audio.get_duration()
    async def unrelated(audio):
        await audio.play()
'''
        errors = api_errors(ast.parse(source))
        self.assertEqual(3, len(errors), errors)
        self.assertIn('requires src', errors[0])
        self.assertTrue(any('synchronous' in error for error in errors))
        self.assertTrue(any('get_duration' in error for error in errors))
        self.assertEqual([], api_errors(ast.parse('def main(ui):\n    ui.audio()\n')))
        self.assertEqual([], api_errors(ast.parse('from nicegui import ui\ndef main(opts):\n    audio = ui.audio(**opts)\n')))

    def test_actual_methods_signatures_and_readonly_properties(self):
        results = ai_chat.execute_tool('read_component_api', {'component': 'ToolResults'})
        self.assertIn('refresh', results['methods'])
        self.assertNotIn('mount', results['methods'])
        self.assertTrue(read_api('ToolJobStatus')['methods']['run']['async'])
        self.assertFalse(read_api('EChart')['properties']['options']['writable'])
        self.assertIn('writer', [p['name'] for p in read_api('ToolOutputs')['methods']['write']['parameters']])
        self.assertIn('error', read_api('os.system'))
        schema = next(item['function'] for item in ai_chat.schemas() if item['function']['name'] == 'read_component_api')
        for component in schema['parameters']['properties']['component']['enum']:
            self.assertNotIn('error', read_api(component), component)

    def test_readonly_assignment_diagnosis_contains_no_state(self):
        from nicegui import ui
        chart = object.__new__(ui.echart)
        with tempfile.TemporaryDirectory() as directory:
            path = (Path(directory) / 'tool.py').resolve()
            path.write_text('def fail(chart):\n    chart.options = {"secret": "private"}\n')
            namespace = {}
            exec(compile(path.read_text(), str(path), 'exec'), namespace)
            try:
                namespace['fail'](chart)
            except AttributeError as error:
                info = diagnose(error, path)
            self.assertEqual('read_only_property', info['problem'])
            self.assertEqual('EChart', info['component'])
            self.assertNotIn('private', str(info))

    def test_dynamic_member_values_are_not_disclosed(self):
        from component.tool_results import ToolResults
        obj = object.__new__(ToolResults)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tool.py'
            path.write_text('def fail(obj):\n    getattr(obj, "private_data")\n')
            namespace = {}
            exec(compile(path.read_text(), str(path), 'exec'), namespace)
            try:
                namespace['fail'](obj)
            except AttributeError as error:
                self.assertIsNone(diagnose(error, path))
