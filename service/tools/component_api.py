"""Read-only API discovery for trusted bundled components, never user modules."""

import ast
import inspect
import re
from pathlib import Path


def components():
    from component.tool_files import ToolFileInput
    from component.tool_results import ToolJobStatus, ToolResults
    from service.files.tool_outputs import ToolOutputs
    from service.tools.tool_jobs import ToolJobs, ToolTask
    from nicegui import ui
    return {cls.__name__: cls for cls in (
        ToolFileInput, ToolResults, ToolJobStatus, ToolOutputs, ToolJobs, ToolTask,
        ui.echart, ui.table, ui.select, ui.input,
        ui.audio, ui.video, ui.slider, ui.timer, ui.button,
        ui.left_drawer, ui.right_drawer, ui.header, ui.footer,
    )}


def parameters(callable_):
    """Expose call shape without serializing defaults or runtime values."""
    try:
        return [{"name": p.name, "kind": p.kind.name,
                 "required": p.default is inspect.Parameter.empty and p.kind not in (
                     inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)}
                for p in inspect.signature(callable_).parameters.values()
                if p.name not in {"self", "cls"}]
    except (TypeError, ValueError):
        return []


def read_api(component):
    registry = components()
    if component not in registry:
        return {"error": "Unknown component", "available": sorted(registry)}
    cls = registry[component]
    methods, properties = {}, {}
    # getattr_static prevents invoking descriptors or reading instance state.
    for name in dir(cls):
        if name.startswith('_'):
            continue
        value = inspect.getattr_static(cls, name)
        if isinstance(value, property):
            properties[name] = {"writable": value.fset is not None}
        elif inspect.isdatadescriptor(value):
            properties[name] = {"writable": hasattr(type(value), '__set__')}
        elif inspect.isfunction(value):
            annotation = inspect.signature(value).return_annotation
            methods[name] = {"parameters": parameters(value), "async": inspect.iscoroutinefunction(value),
                             "returns_none": annotation in (None, type(None), 'None')}
    result = {"component": component, "constructor": parameters(cls),
              "methods": methods, "properties": properties}
    from core.tool_api_contracts import TOOL_UI_CONTEXT
    result['host_context'] = TOOL_UI_CONTEXT
    if component == 'ToolResults':
        result['usage'] = 'Constructor renders immediately in the current UI container. outputs is a ToolOutputs instance. Call refresh() after publishing outputs.'
    elif component in {'Audio', 'Video'}:
        result['usage'] = (
            'src is required. play(), pause(), seek(seconds) and set_source(source) are synchronous and return None; do not await them. '
            'There are no get_duration()/get_position() methods. Use loadedmetadata/timeupdate events with explicit event args, '
            'or supported frontend property access. volume is an HTMLMediaElement property, not a declared component prop.'
        )
    elif component == 'Timer':
        result['usage'] = 'The callback is invoked repeatedly and may be async. Each invocation should finish; do not put an infinite loop inside a repeating timer callback.'
    elif component in TOOL_UI_CONTEXT['unsupported_page_components']:
        result['allowed_in_tool'] = False
        result['usage'] = 'This is a page-root layout component. Calabash owns the page layout and calls tool main() inside a Column. Use local ui.row()/ui.column() navigation or header/footer content instead; changing fixed=False does not remove this restriction.'
    return result


def validation_diagnosis(content):
    """Recompute trusted contract facts; never forward exception text or source."""
    from core.tool_api_contracts import api_errors
    try:
        errors = api_errors(ast.parse(content))
    except SyntaxError as error:
        return {'problem': 'invalid_syntax', 'lines': [error.lineno] if error.lineno else []}
    if not errors:
        return {'problem': 'invalid_entrypoint', 'details': ['Tool requires a top-level main() function.'], 'lines': []}
    lines = [int(match.group(1)) for error in errors if (match := re.match(r'^Line ([1-9][0-9]*):', error))]
    return {'problem': 'invalid_component_api', 'details': errors, 'lines': sorted(set(lines))}


def diagnose(error, path):
    """Return component/member facts only, without raw errors, locals or values."""
    registry = components()
    if isinstance(error, (TypeError, RuntimeError)):
        from core.tool_api_contracts import component_call_diagnostics
        try:
            diagnostics = component_call_diagnostics(ast.parse(path.read_text(encoding='utf-8')))
        except (OSError, SyntaxError, UnicodeError):
            return None
        lines = set()
        tb = error.__traceback__
        while tb:
            if Path(tb.tb_frame.f_code.co_filename).resolve() == path.resolve():
                lines.add(tb.tb_lineno)
            tb = tb.tb_next
        for item in diagnostics:
            if item['line'] in lines:
                return {**item, 'next_action': 'Call read_component_api for the actual component contract before editing.'}
    tb = error.__traceback__
    while tb:
        if Path(tb.tb_frame.f_code.co_filename).resolve() == path.resolve():
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (OSError, SyntaxError, UnicodeError):
                return None
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute) or node.lineno != tb.tb_lineno:
                    continue
                if not isinstance(node.value, ast.Name) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', node.attr):
                    continue
                obj = tb.tb_frame.f_locals.get(node.value.id)
                label = next((name for name, cls in registry.items() if type(obj) is cls), None)
                if label is None:
                    continue
                if isinstance(error, AttributeError) and error.obj is obj and error.name == node.attr:
                    return {"component": label, "member": node.attr, "problem": "missing_attribute",
                            "next_action": "Call read_component_api for the real API before editing."}
                if isinstance(error, AttributeError) and isinstance(node.ctx, ast.Store):
                    member = inspect.getattr_static(type(obj), node.attr, None)
                    if isinstance(member, property) and member.fset is None:
                        return {"component": label, "member": node.attr, "problem": "read_only_property",
                                "next_action": "Call read_component_api; update mutable property contents in place when supported."}
        tb = tb.tb_next
    return None
