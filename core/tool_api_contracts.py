"""Conservative, non-executing checks for known tool API mistakes."""

import ast


RESULTS_MOUNT_HINT = "ToolResults renders in its constructor; remove mount() and use refresh() after writing results."
ECHART_OPTIONS_HINT = "EChart.options is read-only; update chart.options in place, then call chart.update()."
TOOL_UI_CONTEXT = {
    'mount': 'Tool main() is rendered inside a Calabash-owned Column, not the page root.',
    'page_layout_owner': 'Calabash',
    'unsupported_page_components': ['LeftDrawer', 'RightDrawer', 'Header', 'Footer'],
    'alternative': 'Build local navigation, headers and footers with ui.row()/ui.column() inside the tool content.',
}


def component_call_diagnostics(tree):
    """Check statically known component calls in Calabash's tool context."""
    diagnostics = []
    constructors = {"nicegui.ui.audio": "Audio", "nicegui.ui.video": "Video"}
    page_components = {f'nicegui.ui.{name}': kind for name, kind in (
        ('left_drawer', 'LeftDrawer'), ('right_drawer', 'RightDrawer'), ('header', 'Header'), ('footer', 'Footer'),
    )}

    def scan(scope, inherited_aliases, inherited_bindings):
        nodes, children, declarations = [], [], set()

        def collect(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                children.append(node)
                return
            if isinstance(node, (ast.ClassDef, ast.Lambda)):
                if isinstance(node, ast.ClassDef):
                    declarations.add(node.name)
                return
            nodes.append(node)
            for child in ast.iter_child_nodes(node):
                collect(child)

        for statement in scope.body:
            collect(statement)
        writes = {}
        for node in nodes:
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                writes[node.id] = writes.get(node.id, 0) + 1
        shadowed = set(writes) | {child.name for child in children} | declarations
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            shadowed.update(arg.arg for arg in [*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs])
            shadowed.update(arg.arg for arg in (scope.args.vararg, scope.args.kwarg) if arg)
        aliases = {key: value for key, value in inherited_aliases.items() if key not in shadowed}
        bindings = {key: value for key, value in inherited_bindings.items() if key not in shadowed}
        for node in nodes:
            if isinstance(node, ast.ImportFrom):
                for item in node.names:
                    alias = item.asname or item.name
                    if alias not in writes:
                        aliases[alias] = f"{node.module}.{item.name}"
            elif isinstance(node, ast.Import):
                for item in node.names:
                    alias = item.asname or item.name.split('.')[0]
                    if alias not in writes:
                        aliases[alias] = item.name if item.asname else item.name.split('.')[0]

        def qualified(node):
            if isinstance(node, ast.Name):
                return aliases.get(node.id, '')
            if isinstance(node, ast.Attribute):
                return f"{qualified(node.value)}.{node.attr}"
            return ''

        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
                call = node.value
                while isinstance(call.func, ast.Attribute) and call.func.attr in {'props', 'classes', 'style'} and isinstance(call.func.value, ast.Call):
                    call = call.func.value
                kind = constructors.get(qualified(call.func))
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if kind and isinstance(target, ast.Name) and writes.get(target.id) == 1:
                        bindings[target.id] = kind

        def add(node, kind, member, problem, message, **details):
            diagnostics.append({"line": node.lineno, "component": kind, "member": member,
                                "problem": problem, "message": message, **details})

        for node in nodes:
            if isinstance(node, ast.Call):
                page_kind = page_components.get(qualified(node.func))
                if page_kind:
                    add(node, page_kind, '__init__', 'invalid_host_layout',
                        f'{page_kind} requires the page root, but Calabash tools render inside a Column. Use local ui.row()/ui.column() layouts instead; do not move tool widgets outside the host shell.')
                kind = constructors.get(qualified(node.func))
                if kind and not node.args and not any(k.arg in {'src', None} for k in node.keywords):
                    add(node, kind, '__init__', 'missing_required_argument', f"{kind} requires src; provide a source when constructing it.", parameters=['src'])
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                kind = bindings.get(node.value.id)
                if kind and node.attr in {'get_duration', 'get_position'}:
                    add(node, kind, node.attr, 'missing_attribute', f"{kind} has no {node.attr}(); use supported media events or frontend property access.")
            if isinstance(node, ast.Await) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
                method = node.value.func
                kind = bindings.get(method.value.id) if isinstance(method.value, ast.Name) else None
                if kind and method.attr in {'play', 'pause', 'seek', 'set_source'}:
                    add(node, kind, method.attr, 'not_awaitable', f"{kind}.{method.attr}() is synchronous and returns None; do not await it.")
        for child in children:
            scan(child, aliases, bindings)

    scan(tree, {}, {})
    return diagnostics


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
    errors.extend(f"Line {item['line']}: {item['message']}" for item in component_call_diagnostics(tree))
    return errors
