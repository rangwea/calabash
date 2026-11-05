"""Derive a typed local API client from Python annotations without importing tools."""

import ast
import json
import re


class ContractError(ValueError):
    def __init__(self, file, node, reason):
        self.diagnostic = {'file': file, 'line': getattr(node, 'lineno', 1),
                           'code': 'API_CONTRACT', 'message': reason}
        super().__init__(reason)


def extract(files):
    models = {}
    functions = []
    for file, source in files.items():
        if not file.startswith('backend/') or not file.endswith('.py'):
            continue
        tree = ast.parse(source, filename=file)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                if node.name in models:
                    raise ContractError(file, node, 'Contract model names must be unique across backend modules')
                models[node.name] = (file, node)
        functions.extend((file, node) for node in ast.walk(tree)
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))

    used = set()

    def annotation(node, file):
        if isinstance(node, ast.Constant):
            if node.value is None:
                return 'null'
            if isinstance(node.value, str):
                try:
                    parsed = ast.parse(node.value, mode='eval').body
                except SyntaxError as error:
                    raise ContractError(file, node, 'Invalid forward annotation') from error
                return annotation(parsed, file)
        if isinstance(node, ast.Name):
            primitive = {'str': 'string', 'int': 'number', 'float': 'number', 'bool': 'boolean', 'None': 'null'}
            if node.id in primitive:
                return primitive[node.id]
            if node.id in models:
                used.add(node.id)
                return node.id
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return '(' + annotation(node.left, file) + ' | ' + annotation(node.right, file) + ')'
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            kind = node.value.id
            args = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
            if kind == 'Literal' and all(isinstance(arg, ast.Constant) and type(arg.value) in (str, int, bool) for arg in args):
                return '(' + ' | '.join(json.dumps(arg.value) for arg in args) + ')'
            if kind in {'list', 'List'} and len(args) == 1:
                return 'Array<' + annotation(args[0], file) + '>'
            if kind == 'Optional' and len(args) == 1:
                return '(' + annotation(args[0], file) + ' | null)'
            if kind == 'Union':
                return '(' + ' | '.join(annotation(arg, file) for arg in args) + ')'
            if kind in {'dict', 'Dict'} and len(args) == 2 and isinstance(args[0], ast.Name) and args[0].id == 'str':
                return 'Record<string, ' + annotation(args[1], file) + '>'
        raise ContractError(file, node, 'Unsupported API type. Use explicit Pydantic models, primitives, Literal, list, dict[str, T] or optional types')

    operations = []
    for file, function in functions:
        for decorator in function.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr.upper()
            options = {item.arg: item.value for item in decorator.keywords}
            if method not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'} or 'operation_id' not in options:
                continue
            if any(key == 'response_class' or key.startswith('response_model_exclude') or key == 'response_model_include' for key in options):
                raise ContractError(file, decorator, 'Typed JSON API operations must return the complete declared response model')
            operation = options['operation_id']
            if not isinstance(operation, ast.Constant) or not isinstance(operation.value, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', operation.value):
                raise ContractError(file, decorator, 'Use a literal snake_case operation_id')
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant) or not isinstance(decorator.args[0].value, str):
                raise ContractError(file, decorator, 'API paths must be literal strings')
            path = decorator.args[0].value
            if len(path) > 200 or not re.fullmatch(r'/api/(?!sdk(?:/|$))[a-zA-Z0-9_/{}/-]+', path):
                raise ContractError(file, decorator, 'Use a local /api/ route outside the reserved SDK namespace')
            response = options.get('response_model', function.returns)
            if response is None:
                raise ContractError(file, function, 'Typed API operations need response_model or a return annotation')
            entry = {'name': operation.value, 'method': method, 'path': path,
                     'response': annotation(response, file), 'query': {}, 'params': {}, 'body': None}
            arguments = function.args.posonlyargs + function.args.args
            defaults = dict(zip([arg.arg for arg in arguments[-len(function.args.defaults):]], function.args.defaults)) if function.args.defaults else {}
            arguments += function.args.kwonlyargs
            defaults.update({arg.arg: value for arg, value in zip(function.args.kwonlyargs, function.args.kw_defaults) if value is not None})
            for argument in arguments:
                if isinstance(argument.annotation, ast.Name) and argument.annotation.id in {'Request', 'Response'}:
                    continue
                if argument.annotation is None:
                    raise ContractError(file, argument, 'Every typed API parameter needs an explicit annotation')
                type_name = annotation(argument.annotation, file)
                default = defaults.get(argument.arg)
                optional = argument.arg in defaults
                if isinstance(default, ast.Call):
                    if not isinstance(default.func, ast.Name) or default.func.id not in {'Body', 'Query', 'Path'}:
                        raise ContractError(file, argument, 'Use literal parameter defaults or Body/Query/Path declarations')
                    kwargs = {item.arg: item.value for item in default.keywords}
                    if {'alias', 'embed', 'validation_alias'} & kwargs.keys():
                        raise ContractError(file, argument, 'Typed API parameters must use their Python names without embedding or aliases')
                    value = kwargs.get('default', default.args[0] if default.args else None)
                    optional = value is not None and not (isinstance(value, ast.Constant) and value.value is Ellipsis)
                field = {'type': type_name, 'optional': optional}
                if '{' + argument.arg + '}' in path:
                    entry['params'][argument.arg] = {**field, 'optional': False}
                elif isinstance(argument.annotation, ast.Name) and argument.annotation.id in models or isinstance(argument.annotation, ast.Constant) and argument.annotation.value in models:
                    if entry['body'] is not None or method == 'GET':
                        raise ContractError(file, argument, 'Use one Pydantic request body for each write operation')
                    entry['body'] = field
                else:
                    if type_name.startswith(('Array<', 'Record<')) or argument.annotation is not None and not isinstance(argument.annotation, (ast.Name, ast.BinOp, ast.Subscript)):
                        raise ContractError(file, argument, 'Use scalar query parameters and direct Pydantic models for request bodies')
                    entry['query'][argument.arg] = field
            if isinstance(options.get('status_code'), ast.Constant) and options['status_code'].value == 204:
                entry['response'] = 'void'
            if set(re.findall(r'{([^}]+)}', path)) != set(entry['params']):
                raise ContractError(file, decorator, 'Every route path parameter needs an annotated argument')
            if any(old['name'] == entry['name'] or (old['path'], old['method']) == (path, method) for old in operations):
                raise ContractError(file, decorator, 'API operation IDs and method/path pairs must be unique')
            operations.append(entry)
            if len(operations) > 100:
                raise ContractError(file, decorator, 'API contract operation limit exceeded')

    declarations = {}
    while used - declarations.keys():
        name = min(used - declarations.keys())
        file, model = models[name]
        if len(declarations) >= 100:
            raise ContractError(file, model, 'API contract model limit exceeded')
        bases = []
        for base in model.bases:
            if isinstance(base, ast.Name) and base.id in models:
                bases.append(annotation(base, file))
            elif not isinstance(base, ast.Name) or base.id != 'BaseModel':
                raise ContractError(file, model, 'Contract models must inherit BaseModel or another contract model')
        if not model.bases:
            raise ContractError(file, model, 'Contract models must inherit BaseModel')
        fields = []
        for field in model.body:
            if isinstance(field, (ast.FunctionDef, ast.AsyncFunctionDef)) and field.decorator_list:
                raise ContractError(file, field, 'Use declarative constraints in shared API models instead of custom serialization or validation decorators')
            if (isinstance(field, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'model_config' for target in field.targets)
                    and isinstance(field.value, ast.Call) and any(item.arg == 'alias_generator' for item in field.value.keywords)):
                raise ContractError(file, field, 'API contract models must not rename fields with alias generators')
            if not isinstance(field, ast.AnnAssign) or not isinstance(field.target, ast.Name):
                continue
            if field.target.id.startswith('_'):
                continue
            optional = field.value is not None
            if isinstance(field.value, ast.Call):
                if not isinstance(field.value.func, ast.Name) or field.value.func.id != 'Field':
                    raise ContractError(file, field, 'Use Field for model defaults and constraints')
                kwargs = {item.arg: item.value for item in field.value.keywords}
                if {'alias', 'validation_alias', 'serialization_alias', 'exclude'} & kwargs.keys():
                    raise ContractError(file, field, 'API contract fields must use their Python names without serialization aliases or exclusions')
                default = kwargs.get('default', field.value.args[0] if field.value.args else None)
                optional = 'default_factory' in kwargs or default is not None and not (isinstance(default, ast.Constant) and default.value is Ellipsis)
            elif isinstance(field.value, ast.Constant) and field.value.value is Ellipsis:
                optional = False
            fields.append(json.dumps(field.target.id) + ('?' if optional else '') + ': ' + annotation(field.annotation, file))
        declarations[name] = 'export interface ' + name + (' extends ' + ', '.join(bases) if bases else '') + ' {\n  ' + ';\n  '.join(fields) + '\n}'
    return {'operations': operations, 'models': declarations}


def client_source(contract):
    def properties(fields):
        return '{ ' + '; '.join(json.dumps(name) + ('?' if field['optional'] else '') + ': ' + field['type'] for name, field in fields.items()) + ' }'

    lines = ["import {request} from './calabash-client'", *contract['models'].values(), 'export const api = {']
    for operation in contract['operations']:
        fields = []
        for key in ('params', 'query'):
            if operation[key]:
                optional = all(field['optional'] for field in operation[key].values())
                fields.append((key, properties(operation[key]), optional))
        if operation['body']:
            fields.append(('body', operation['body']['type'], operation['body']['optional']))
        options = '{ ' + '; '.join([key + ('?' if optional else '') + ': ' + type_name for key, type_name, optional in fields] + ['signal?: AbortSignal']) + ' }'
        default = ' = {}' if all(optional for _, _, optional in fields) else ''
        lines.append('  ' + operation['name'] + ': (options: ' + options + default + ') => request<' + operation['response'] + '>(' + json.dumps(operation['method']) + ', ' + json.dumps(operation['path']) + ', options),')
    return '\n'.join(lines + ['}'])


def prepare(root, files):
    # Generated files live outside source, exports and source revision hashes.
    typed = any('@calabash/api' in source for path, source in files.items() if path.startswith('frontend/'))
    contract = extract(files) if typed else {'operations': [], 'models': {}}
    (root / 'calabash-api.ts').write_text(client_source(contract), encoding='utf-8')
