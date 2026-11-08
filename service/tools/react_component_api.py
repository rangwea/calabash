"""Bounded API lookup from the installed Ant Design TypeScript declarations."""
import json
import os
import re
import sys
from pathlib import Path


def read_api(component, property_name='', *, full=False, offset=0):
    if not isinstance(component, str) or not re.fullmatch(r'[A-Z][A-Za-z0-9]*(?:\.[A-Z][A-Za-z0-9]*)?', component):
        raise ValueError('Use an Ant Design component such as Table, Form.Item or Input')
    if property_name and not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9]{0,79}', property_name):
        raise ValueError('Invalid property name')
    if type(offset) is not int or offset < 0:
        raise ValueError('Invalid declaration offset')
    root = Path(os.environ['CALABASH_FRONTEND_RUNTIME']) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    library = root / 'node_modules/antd'
    name = re.sub(r'(?<!^)([A-Z])', r'-\1', component.split('.')[0]).lower()
    directory = library / 'es' / name
    if not directory.is_dir():
        raise ValueError('Component is not in the bundled library')
    paths = sorted(directory.rglob('*.d.ts'), key=lambda p: (p.name != 'index.d.ts', p.as_posix()))[:30]
    declarations = [(p.relative_to(library).as_posix(), p.read_text(encoding='utf-8')[:64000]) for p in paths]
    result = {'component': component, 'version': json.loads((library / 'package.json').read_text())['version'], 'files': []}
    if full or not property_name:
        total = sum(len(source) for _, source in declarations)
        remaining, skip = (16000 if full else 2400), offset
        for file, source in declarations:
            if skip >= len(source):
                skip -= len(source)
                continue
            page = source[skip:skip + remaining]
            result['files'].append({'file': file, 'declarations': page})
            remaining -= len(page)
            skip = 0
            if not remaining:
                break
        result['next_offset'] = offset + sum(len(item['declarations']) for item in result['files']) if offset + sum(len(item['declarations']) for item in result['files']) < total else None
    else:
        pattern = re.compile(r'(?m)^\s*' + re.escape(property_name) + r'\??\s*[:(][^\n]+')
        for file, source in declarations:
            matches = pattern.findall(source)
            if matches:
                result['files'].append({'file': file, 'declarations': '\n'.join(m.strip() for m in matches[:4])[:2400]})
            if len(result['files']) == 3:
                break
        result['property_name'] = property_name
        if not result['files']:
            result['note'] = 'No local declaration found. This prop may be inherited; read the public interface or check_tool_build. Do not invent component APIs.'
    return result
