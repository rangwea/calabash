import unittest

from service.tools.react_component_api import read_api


class ComponentAPITests(unittest.TestCase):
    def test_real_bundled_button_declarations(self):
        result = read_api('Button', 'disabled')
        self.assertTrue(result['version'])
        self.assertIn('disabled?: boolean', str(result['files']))

    def test_invalid_paths_and_unknown_components_denied(self):
        for name in ('../package', '/secret', 'NotARealComponent'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                read_api(name)

    def test_focused_table_declaration_and_subcomponent(self):
        result = read_api('Table', 'rowSelection')
        self.assertIn('TableRowSelection', str(result['files']))
        self.assertTrue(read_api('Form.Item')['files'])

    def test_full_declarations_are_explicit_and_pageable(self):
        first = read_api('Table', full=True)
        second = read_api('Table', full=True, offset=first['next_offset'])
        self.assertEqual(16000, sum(len(item['declarations']) for item in first['files']))
        self.assertTrue(second['files'])
        self.assertNotEqual(first['files'], second['files'])
        self.assertEqual([], read_api('Table', 'notARealProp')['files'])
