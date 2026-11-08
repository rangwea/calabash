"""Bounded, non-executing inspection of current working source."""

import ast
import hashlib
from functools import lru_cache


@lru_cache(maxsize=32)
def _symbols(content):
    tree = ast.parse(content)
    result = []

    def visit(node, parent=''):
        for child in ast.iter_child_nodes(node):
            path = parent
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                path = f'{parent}.{child.name}' if parent else child.name
                start = min([child.lineno, *[d.lineno for d in child.decorator_list]])
                result.append({'symbol': path, 'kind': 'class' if isinstance(child, ast.ClassDef) else 'function',
                               'start': start, 'end': child.end_lineno})
            visit(child, path)
    visit(tree)
    return result


def inspect_source(content, operation, *, symbol='', query='', offset=0, limit=80):
    if len(content) > 1_000_000:
        return {'error': 'Source is too large'}
    if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 120:
        return {'error': 'offset must be nonnegative; limit must be 1..120'}
    revision = hashlib.sha256(content.encode()).hexdigest()
    lines = content.splitlines()
    base = {'revision': revision, 'total_lines': len(lines), 'executed': False}
    if operation == 'search_code':
        if not isinstance(query, str) or not query or len(query) > 200:
            return {**base, 'error': 'Use a literal query of 1..200 characters'}
        matches = [{'line': i + 1, 'text': line[:240]} for i, line in enumerate(lines) if query in line]
        return {**base, 'matches': matches[offset:offset + limit], 'total_matches': len(matches)}
    try:
        symbols = _symbols(content)
    except SyntaxError as error:
        return {**base, 'error': 'SyntaxError', 'line': error.lineno}
    if operation == 'outline_code':
        return {**base, 'symbols': symbols[offset:offset + limit], 'total_symbols': len(symbols)}
    matches = [item for item in symbols if item['symbol'] == symbol]
    if len(matches) != 1:
        return {**base, 'error': 'Use an unambiguous qualified symbol from outline_code'}
    item = matches[0]
    start = item['start'] - 1 + offset
    end = min(start + limit, item['end'])
    selected, size = [], 0
    for i in range(start, end):
        value = f'{i + 1}: {lines[i]}'
        if size + len(value) > 16000:
            break
        selected.append(value)
        size += len(value)
    return {**base, 'symbol': symbol, 'start': item['start'], 'end': item['end'],
            'content': '\n'.join(selected), 'next_offset': offset + len(selected) if start + len(selected) < item['end'] else None}
