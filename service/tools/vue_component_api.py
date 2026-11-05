"""Read bounded declaration files from the pinned bundled component library."""

import json
import os
import re
import sys
from pathlib import Path


def read_api(component, property_name="", *, full=False, offset=0):
    name = component.removeprefix('el-')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', name):
        raise ValueError('Invalid component')
    root = Path(__file__).resolve().parents[2]
    if getattr(sys, 'frozen', False):
        root = Path(os.environ['CALABASH_FRONTEND_RUNTIME'])
    library = root / 'node_modules/element-plus'
    directory = library / 'es/components' / ('table' if name == 'table-column' else name)
    if not directory.is_dir():
        raise ValueError('Component is not in the bundled library')
    if property_name and not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9-]{0,79}', property_name):
        raise ValueError('Invalid property name')
    if offset < 0 or (offset and not full):
        raise ValueError('Offset requires full declaration mode')

    files = [directory / 'src' / (name + '.d.ts'), directory / 'src/defaults.d.ts']
    if name == 'table':
        files.append(directory / 'src/table/defaults.d.ts')
    if name in {'table', 'table-column'}:
        files.append(directory / 'src/table-column/defaults.d.ts')
    files.extend([directory / 'index.d.ts', directory / 'src' / (name + '.vue.d.ts')])
    declarations = [(path.relative_to(library).as_posix(), path.read_text(encoding='utf-8'))
                    for path in files if path.is_file()]
    result = {'component': 'el-' + name,
              'version': json.loads((library / 'package.json').read_text())['version'],
              'files': []}
    if full:
        start = offset
        remaining = 16000
        for file, source in declarations:
            if offset >= len(source):
                offset -= len(source)
                continue
            page = source[offset:offset + remaining]
            result['files'].append({'file': file, 'declarations': page})
            remaining -= len(page)
            offset = 0
            if not remaining:
                break
        end = start + 16000 - remaining
        result['next_offset'] = end if end < sum(len(source) for _, source in declarations) else None
        return result

    result['note'] = 'Pass property_name for a focused lookup or full=true to page through declarations.'
    if not property_name:
        result['files'] = [{'file': file, 'declarations': source[:1200]}
                           for file, source in declarations[:1]]
        return result

    key = re.sub(r'-([a-z])', lambda match: match[1].upper(), property_name)
    pattern = re.compile(
        r'(?m)(?:^[ \t]*/\*\*(?:(?!\*/)[\s\S])*?\*/\n)?'
        rf'^[ \t]*{re.escape(key)}\??:[^\n]+'
    )
    for file, source in declarations:
        matches = list(dict.fromkeys(match[0].strip() for match in pattern.finditer(source)))
        if matches:
            result['files'].append({'file': file, 'declarations': '\n'.join(matches[:3])[:1200]})
        if len(result['files']) == 2:
            break
    result['property_name'] = property_name
    if result['files'] and name in {'table', 'table-column'} and key == 'reserveSelection':
        result['usage'] = (
            'Set reserve-selection on el-table-column with type="selection" and provide a stable row-key on el-table.'
        )
    elif not result['files']:
        result['note'] = 'No exact declaration found. Check the property name or use full=true.'
    return result
