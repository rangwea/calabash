import tempfile
import unittest
from pathlib import Path

from service.chat import ai_chat
from service.tools.component_api import diagnose, read_api


class ComponentApiTests(unittest.TestCase):
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
