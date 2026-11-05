import unittest

from service.tools.vue_component_api import read_api


class ComponentAPITests(unittest.TestCase):
    def test_real_bundled_button_declarations(self):
        result = read_api('el-button')
        self.assertTrue(result['version'])
        self.assertIn('ButtonProps', str(result['files']))
        self.assertIn('disabled', str(result['files']))

    def test_invalid_paths_and_unknown_components_denied(self):
        for name in ('../package', '/secret', 'not-a-real-component'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                read_api(name)

    def test_selection_prop_returns_focused_declaration_and_usage(self):
        for component in ('el-table', 'el-table-column'):
            result = read_api(component, 'reserve-selection')
            self.assertIn('reserveSelection?: boolean', str(result['files']))
            self.assertIn('row-key', result['usage'])
            self.assertNotIn('currentRowKey', str(result['files']))

    def test_full_declarations_are_explicit_and_pageable(self):
        first = read_api('el-table', full=True)
        second = read_api('el-table', full=True, offset=first['next_offset'])
        self.assertEqual(16000, sum(len(item['declarations']) for item in first['files']))
        self.assertTrue(second['files'])
        self.assertNotEqual(first['files'], second['files'])
        self.assertEqual([], read_api('el-table', 'not-a-real-prop')['files'])
