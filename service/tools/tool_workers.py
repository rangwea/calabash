"""Shared Python tool instances and short-lived frontend compiler invocations."""

import asyncio
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

from core.i18n import t
from core.local_paths import app_dir
from service.tools import tool_bundles as bundles
from service.tools.owned_process import spawn, stop

ROOT = Path(__file__).resolve().parents[2]


def frontend_runtime():
    if getattr(sys, 'frozen', False):
        root = Path(os.environ.get('CALABASH_FRONTEND_RUNTIME', ROOT / 'frontend-runtime'))
        node = root / ('node.exe' if os.name == 'nt' else 'node')
    else:
        root = ROOT
        node = shutil.which('node')
    if not node or not Path(node).is_file() or not (root / 'scripts/tool_frontend.mjs').is_file():
        raise ValueError('Bundled frontend runtime unavailable')
    return str(node), root / 'scripts/tool_frontend.mjs'



class FrontendBuildError(ValueError):
    def __init__(self, root):
        self.root = root
        self.diagnostics = build_diagnostics(root)
        super().__init__('Frontend build failed; inspect preview check results')


def build_diagnostics(root):
    # Never expose raw compiler output: it can contain source literals and paths.
    with (root / 'build.log').open('rb') as handle:
        handle.seek(max(0, handle.seek(0, 2) - 65536))
        output = handle.read().decode('utf-8', errors='replace')
    result = []
    for match in re.finditer(r'(frontend/[a-zA-Z0-9_./-]+)\((\d+),(\d+)\): error (TS\d+):([^\r\n]*)', output):
        path, line, column, code, detail = match.groups()
        try:
            bundles.safe_path(path)
        except ValueError:
            continue
        message = {'TS2322': '组件值类型不匹配，请处理空值或联合类型',
                   'TS2353': '组件不支持此属性或事件，请查询组件接口',
                   'TS2339': '属性不存在，请检查对象或组件接口',
                   'TS2307': '无法解析模块，请使用内置库或正确的相对路径'}.get(code, 'TypeScript 检查失败，请检查此处代码')
        item = {'file': path, 'line': int(line), 'column': int(column), 'code': code, 'message': message}
        from service.tools.type_diagnostics import type_evidence
        item.update(type_evidence(detail))
        if item not in result:
            result.append(item)
        if len(result) >= 20:
            break
    diagnostic = root / 'build-diagnostics.json'
    if not result and diagnostic.is_file() and not diagnostic.is_symlink() and diagnostic.stat().st_size < 8192:
        try:
            value = json.loads(diagnostic.read_text())
            item = {'code': 'VITE', 'message': 'React 编译失败，请检查此处语法或导入'}
            if value.get('code') in {'API_CONTRACT', 'SOURCE'}:
                item = {'code': value['code'], 'message': str(value.get('message', '源码检查失败'))[:300]}
            if isinstance(value.get('file'), str) and value['file'].startswith(('frontend/', 'backend/')):
                item['file'] = bundles.safe_path(value['file'])
            for key in ('line', 'column'):
                if type(value.get(key)) is int and 0 < value[key] < 1000000:
                    item[key] = value[key]
            result.append(item)
        except (ValueError, OSError, TypeError, AttributeError):
            pass
    return result or [{'message': '前端构建失败，请检查语法和导入；详细错误保留在本机构建日志'}]


async def build_bundle(files):
    root = app_dir() / 'builds' / uuid4().hex
    root.mkdir(parents=True, mode=0o700)
    try:
        bundles.validate(files)
    except (ValueError, SyntaxError) as error:
        diagnostic = {'code': 'SOURCE', 'message': 'Working source is incomplete or invalid. Check tool.json and the required frontend/App.tsx and backend/main.py files.'}
        if isinstance(error, SyntaxError):
            diagnostic.update(file=error.filename, line=error.lineno, message='Python syntax error. Read this line in the working source and correct it.')
        (root / 'build.log').write_text('Working source validation failed', encoding='utf-8')
        (root / 'build-diagnostics.json').write_text(json.dumps(diagnostic), encoding='utf-8')
        raise FrontendBuildError(root) from error
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    from service.tools.api_contracts import ContractError, prepare
    try:
        prepare(root, files)
    except ContractError as error:
        (root / 'build.log').write_text('API contract validation failed', encoding='utf-8')
        (root / 'build-diagnostics.json').write_text(json.dumps(error.diagnostic), encoding='utf-8')
        raise FrontendBuildError(root) from error
    node, script = frontend_runtime()
    with (root / 'build.log').open('ab') as output:
        try:
            process = await spawn([node, str(script), 'build', str(root)], group=True, stdin=subprocess.PIPE, stdout=output, stderr=output)
            try:
                await asyncio.to_thread(process.wait, timeout=90)
            finally:
                await asyncio.to_thread(stop, process, group=True)
        except BaseException as error:
            if isinstance(error, asyncio.CancelledError):
                shutil.rmtree(root, ignore_errors=True)
            if isinstance(error, subprocess.TimeoutExpired):
                raise FrontendBuildError(root) from error
            raise
        if process.returncode:
            raise FrontendBuildError(root)

    return root


@dataclass
class Worker:
    project: str
    name: str
    revision: str
    root: Path
    port: int
    token: str
    app: object
    sdk: object
    host_token: str = ''
    log_run: object = None
    server: object = None
    server_task: object = None
    active_calls: int = 0
    lifetime: object = None

    @property
    def alive(self):
        return self.server_task is not None and not self.server_task.done()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}/api/sdk/session?session={self.token}'

    async def stop(self):
        from service.tools.shared_runtime import unload
        await self.sdk.shutdown()
        await self.lifetime.__aexit__(None, None, None)
        if self.log_run:
            self.log_run.close()
        unload(self.app.state.namespace)
        if self.root.parent == app_dir() / 'runtime' and not self.root.is_symlink():
            await asyncio.to_thread(shutil.rmtree, self.root, ignore_errors=True)


class ToolWorkers:
    def __init__(self):
        self.items = {}
        self.failures = {}
        self.lock = asyncio.Lock()
        self.start_locks = {}
        self.detached = set()
        self.schedule_holds = {}
        self.stopping = False
        from service.tools.shared_runtime import SharedRuntime
        self.gateway = SharedRuntime()

    def current(self, project, name, chat_id=None):
        key = self.key(project, name, chat_id)
        return self.items.get(key) or self.failures.get(key)

    def key(self, project, name, chat_id=None):
        return (project, name, chat_id)

    def is_open(self, project, name):
        return any((item.project, item.name) == (project, name) and item.alive for item in self.items.values())

    async def running(self, project, name):
        for item in tuple(self.items.values()):
            if (item.project, item.name) == (project, name) and item.alive and (await self.status(item)).get('running'):
                return True
        return False

    @asynccontextmanager
    async def publication(self, project, name):
        async with self.lock:
            locked = []
            async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
                try:
                    for item in tuple(self.items.values()):
                        if (item.project, item.name) == (project, name) and item.alive:
                            if item.active_calls:
                                raise ValueError('Wait for active tool requests before saving')
                            response = await client.post(f'http://127.0.0.1:{item.port}/api/sdk/publication-lock?frozen=true', headers={'Authorization': 'Bearer ' + item.token, 'X-Calabash-Host': item.host_token})
                            if response.status_code != 200:
                                raise ValueError('Stop the running tool before replacing it')
                            locked.append(item)
                    yield
                finally:
                    for item in locked:
                        try:
                            await client.post(f'http://127.0.0.1:{item.port}/api/sdk/publication-lock?frozen=false', headers={'Authorization': 'Bearer ' + item.token, 'X-Calabash-Host': item.host_token})
                        except httpx.HTTPError:
                            pass  # A stopped process cannot accept new jobs.

    async def open(self, project, name, chat_id=None):
        if self.stopping:
            raise ValueError(t('应用正在安全退出，暂不接受新任务'))
        key = self.key(project, name, chat_id)
        async with self.start_locks.setdefault(key, asyncio.Lock()):
            if self.stopping:
                raise ValueError(t('应用正在安全退出，暂不接受新任务'))
            self.detached.discard(key)
            previous = self.items.get(key)
            if previous:
                if previous.alive:
                    return previous
                if previous.sdk.status()['running'] or previous.active_calls:
                    raise ValueError(t('工具界面已断开，请等待当前任务完成后重新打开'))
                await self.gateway.remove(previous)
                await previous.stop()
                self.items.pop(key, None)
            if chat_id and not bundles.directory(project, name, chat_id).exists():
                from service.tools import work_drafts
                owner = 'preview-' + uuid4().hex
                try:
                    work_drafts.ensure(project, name, owner)
                finally:
                    work_drafts.release(owner)
            source = bundles.read(project, name, chat_id)
            meta = bundles.validate(source['files'])
            from service.capabilities.tool_capabilities import require_tool_capabilities
            requirements = meta.get('requires', '')
            require_tool_capabilities(requirements)
            root = app_dir() / 'runtime' / uuid4().hex
            log_run = None
            try:
                root.mkdir(parents=True, mode=0o700)
                for relative, content in source['files'].items():
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
                    if relative.startswith('backend/'):
                        path.chmod(0o400)
                if chat_id:
                    from service.tools.tool_checks import checks
                    async with checks.verified(project, name, chat_id, source) as built:
                        shutil.copytree(built / 'dist', root / 'dist')
                else:
                    published_dist = bundles.directory(project, name) / 'dist'
                    if not (published_dist / 'index.html').is_file():
                        raise ValueError('Publish a built tool before opening')
                    shutil.copytree(published_dist, root / 'dist')
                from service.tools.shared_runtime import socket_for_origin
                sock = socket_for_origin()
                port = sock.getsockname()[1]
                token, host_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                config = {'root': str(root), 'source_root': str(root), 'project': project, 'name': name, 'port': port,
                          'token': token, 'origin': f'http://127.0.0.1:{port}', 'revision': source['revision'], 'host_token': host_token,
                          'partitioned_session': os.environ.get('CALABASH_HARNESS_EMBEDDED') == '1', 'diagnostic_owner': chat_id or 'published'}
                from backend.tool_worker import create_tool_app
                from core import tool_run_logs
                from service.tools.tool_execution import io
                log_run = tool_run_logs.start(project, name, preview_key=chat_id)
                with log_run.context():
                    app = await io(create_tool_app, config)
                sdk = app.state.sdk
                sdk.loop = asyncio.get_running_loop()
                lifetime = app.router.lifespan_context(app)
                await lifetime.__aenter__()
                worker = Worker(project, name, source['revision'], root, port, token, app, sdk,
                                host_token=host_token, log_run=log_run, lifetime=lifetime)
                await self.gateway.listen(worker, sock)
            except BaseException:
                if 'sock' in locals():
                    sock.close()
                if 'worker' in locals():
                    await self.gateway.remove(worker)
                    await worker.stop()
                elif log_run:
                    log_run.close()
                await asyncio.to_thread(shutil.rmtree, root, ignore_errors=True)
                raise
            self.items[key] = worker
            self.failures.pop(key, None)
            return worker

    async def status(self, worker):
        return worker.sdk.status()

    async def close(self, project, name, chat_id=None):
        key = self.key(project, name, chat_id)
        async with self.start_locks.setdefault(key, asyncio.Lock()):
            await self._close(project, name, chat_id)

    async def _close(self, project, name, chat_id=None):
        key = self.key(project, name, chat_id)
        worker = self.items.get(key)
        if worker:
            if self.schedule_holds.get(key):
                self.detached.add(key)
                return
            if worker.active_calls:
                raise ValueError('Wait for the active tool request before closing')
            state = await self._prepare_exit(worker) if worker.alive else {'running': False}
            if state.get('running'):
                async with httpx.AsyncClient(trust_env=False) as client:
                    await client.post(f'http://127.0.0.1:{worker.port}/api/sdk/cancel', headers={'Authorization': 'Bearer ' + worker.token})
                raise ValueError('Safe stop requested; wait for current item to finish before closing')
            await self.gateway.remove(worker)
            await worker.stop()
            self.items.pop(key, None)
            self.detached.discard(key)

    async def detach(self, project, name, chat_id):
        key = self.key(project, name, chat_id)
        worker = self.items.get(key)
        self.detached.add(key)
        if worker and worker.alive and (await self.status(worker)).get('running'):
            self.detached.add(key)
        else:
            await self.close(project, name, chat_id)

    async def shutdown(self):
        self.stopping = True
        # Drain starts that have not yet registered their process handles.
        for lock in tuple(self.start_locks.values()):
            async with lock:
                pass
        for key, worker in tuple(self.items.items()):
            await self.gateway.remove(worker)
            await worker.stop()
            self.items.pop(key, None)

    async def _prepare_exit(self, worker):
        return worker.sdk.request_stop()

    async def prepare_exit(self):
        self.stopping = True
        for lock in tuple(self.start_locks.values()):
            async with lock:
                pass
        ready = True
        for worker in tuple(self.items.values()):
            state = await self._prepare_exit(worker)
            if worker.active_calls or state.get('running'):
                ready = False
        return ready

    async def monitor(self):
        while True:
            for key, item in tuple(self.items.items()):
                broken = not item.alive
                if broken:
                    self.detached.add(key)
            for key in tuple(self.detached):
                item = self.items.get(key)
                try:
                    if self.schedule_holds.get(key):
                        continue
                    if item and (not item.alive or not (await self.status(item)).get('running')) and key in self.detached:
                        await self.close(*key)
                except (httpx.HTTPError, ValueError):
                    continue  # Unknown state must not terminate a possible writer.
            await asyncio.sleep(.2)


workers = ToolWorkers()
