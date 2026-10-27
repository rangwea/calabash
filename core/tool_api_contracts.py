"""Conservative, non-executing checks for known tool API mistakes."""

import ast


RESULTS_MOUNT_HINT = "ToolResults renders in its constructor; remove mount() and use refresh() after writing results."
ECHART_OPTIONS_HINT = "EChart.options is read-only; update chart.options in place, then call chart.update()."


def api_errors(tree):
    """Recognize direct constructor bindings only; do not infer arbitrary types."""
    aliases = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
        elif isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]

    def name(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, '')
        if isinstance(node, ast.Attribute):
            return f"{name(node.value)}.{node.attr}"
        return ''

    errors = []
    # A binding is trusted only when assigned exactly once in this lexical scope.
    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        nodes = []

        def collect(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                return
            nodes.append(node)
            for child in ast.iter_child_nodes(node):
                collect(child)

        for statement in scope.body:
            collect(statement)
        writes = {}
        for node in nodes:
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                writes[node.id] = writes.get(node.id, 0) + 1
        bindings = {}
        for node in nodes:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                value = node.value
                while isinstance(value.func, ast.Attribute) and value.func.attr in {'classes', 'props', 'style'} and isinstance(value.func.value, ast.Call):
                    value = value.func.value
                for target in node.targets:
                    if isinstance(target, ast.Name) and writes.get(target.id) == 1:
                        bindings[target.id] = name(value.func)
        for node in nodes:
            if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
                continue
            kind = bindings.get(node.value.id)
            if kind == 'component.tool_results.ToolResults' and node.attr == 'mount':
                errors.append(f"Line {node.lineno}: {RESULTS_MOUNT_HINT}")
            if kind == 'nicegui.ui.echart' and node.attr == 'options' and isinstance(node.ctx, ast.Store):
                errors.append(f"Line {node.lineno}: {ECHART_OPTIONS_HINT}")
    return errors
