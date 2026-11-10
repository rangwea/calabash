"""Bounded, value-free evidence for one preview execution; never executes APIs."""
import json
import os
import re
import time
from uuid import uuid4

from service.tools.check_records import directory
from service.tools.tool_bundles import safe_path

MESSAGES = {
    'PAGE_READY': '页面已完成首次挂载；不代表业务操作通过',
    'PAGE_EMPTY': '页面尚未显示内容，请检查入口组件和初始渲染',
    'PAGE_SCRIPT': '页面脚本异常，请检查对应位置',
    'PAGE_RESOURCE': '页面资源加载失败，请检查入口与模块引用',
    'MODULE_HTTP': '预览共享模块无法加载，请检查宿主资源路由',
    'API_ROUTE': '实际注册路由与静态接口契约不一致',
    'API_INPUT': '实际请求参数与接口契约不一致',
    'API_RESPONSE': '接口返回值与响应模型不一致',
    'API_FAILURE': '接口执行失败，请检查异常位置',
    'API_CONTRACT': '接口契约无法解析，请补充明确的请求和响应类型',
}


def clean(item):
    code = item.get('code')
    if code not in MESSAGES:
        raise ValueError('Unknown preview diagnostic')
    result = {'code': code, 'message': MESSAGES[code]}
    if code == 'PAGE_SCRIPT':
        result['location_kind'] = 'transformed_runtime_position_not_source_line'
    file = item.get('file')
    if isinstance(file, str) and file.startswith(('frontend/', 'backend/')):
        try:
            result['file'] = safe_path(file)
        except ValueError:
            pass
    for key in ('line', 'column'):
        value = item.get(key)
        if type(value) is int and 0 < value < 1000000:
            result[key] = value
    for key in ('operation', 'exception'):
        value = item.get(key)
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', value):
            result[key] = value
    if code in {'API_INPUT', 'API_RESPONSE'} and isinstance(item.get('fields'), list):
        fields = []
        kinds = {'missing', 'int_parsing', 'int_type', 'float_parsing', 'float_type', 'bool_parsing', 'bool_type', 'string_type', 'list_type', 'dict_type', 'model_type', 'literal_error', 'extra_forbidden'}
        for field in item['fields'][:20]:
            if not isinstance(field, dict):
                continue
            location = field.get('location', [])
            if not isinstance(location, list):
                continue
            location = [part for part in location[:8] if type(part) is int and 0 <= part < 1000000 or isinstance(part, str) and (part == '<field>' or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', part))]
            fields.append({'location': location, 'kind': field.get('kind') if field.get('kind') in kinds else 'invalid'})
        result['fields'] = fields
    status = item.get('status')
    if type(status) is int and 100 <= status <= 599:
        result['status'] = status
    return result


class PreviewDiagnostics:
    def __init__(self, project, name, owner, run_id, revision):
        self.identity = {'project': project, 'name': name, 'owner': owner, 'run_id': run_id, 'revision': revision}
        self.enabled = bool(re.fullmatch(r'[a-f0-9]{32}', run_id or '') and re.fullmatch(r'[a-f0-9]{64}', revision or ''))
        self.page = 'pending'
        self.interfaces = 'pending'
        self.events = []
        self.verified = 0
        self.untyped = 0

    def event(self, item):
        value = clean(item)
        if value['code'] == 'PAGE_READY':
            if self.page != 'failed':
                self.page = 'ready'
        elif value['code'].startswith('PAGE_') or value['code'] == 'MODULE_HTTP':
            self.page = 'failed'
        if value not in self.events and len(self.events) < 30:
            self.events.append(value)
        self.persist()

    def persist(self):
        try:
            self.save()
        except (OSError, ValueError):
            from core.logger import get_logger
            get_logger(__name__).warning('Preview diagnostics could not be persisted')

    def report(self):
        return {**self.identity, 'page': self.page, 'interfaces': self.interfaces,
                'verified_operations': self.verified, 'untyped_operations': self.untyped,
                'business_verified': False, 'evidence': 'untrusted_runtime_metadata',
                'diagnostics': [clean(item) for item in self.events]}

    def save(self):
        if not self.enabled:
            return
        path = directory(self.identity['project'], self.identity['name'], self.identity['owner']) / 'runs'
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = path / (self.identity['run_id'] + '.json')
        if path.is_symlink() or target.is_symlink():
            raise ValueError('Linked runtime diagnostics forbidden')
        temporary = path / ('.' + uuid4().hex + '.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as handle:
                os.chmod(temporary, 0o600)
                json.dump(self.report(), handle, ensure_ascii=False)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        old = sorted((item for item in path.glob('*.json') if item.is_file() and not item.is_symlink()), key=lambda item: item.stat().st_mtime, reverse=True)
        for index, item in enumerate(old):
            if item != target and (index >= 5 or time.time() - item.stat().st_mtime > 7 * 86400):
                item.unlink(missing_ok=True)

    def check_interfaces(self, app, files):
        from fastapi.routing import APIRoute

        from service.tools.api_contracts import ContractError, extract
        routes = [route for route in app.routes if isinstance(route, APIRoute) and route.path.startswith('/api/') and not route.path.startswith('/api/sdk/')]
        self.untyped = sum(not route.operation_id for route in routes)
        try:
            contract = extract(files)
        except (ContractError, SyntaxError, ValueError) as error:
            self.interfaces = 'failed'
            self.event({**(error.diagnostic if isinstance(error, ContractError) else {}), 'code': 'API_CONTRACT'})
            return
        self.interfaces = ('partial' if self.untyped else 'passed') if contract['operations'] else 'not_checked'
        for item in contract['operations']:
            matches = [route for route in routes if route.path == item['path'] and item['method'] in route.methods and route.operation_id == item['name']]
            valid = len(matches) == 1
            if valid:
                route = matches[0]
                valid = set(item['query']) == {field.name for field in route.dependant.query_params} and set(item['params']) == {field.name for field in route.dependant.path_params}
                valid = valid and bool(item['body']) == bool(route.dependant.body_params)
                valid = valid and (item['response'] == 'void' or route.response_model is not None)
            if valid:
                self.verified += 1
            else:
                self.interfaces = 'failed'
                self.event({'code': 'API_ROUTE', 'operation': item['name']})
        self.persist()
