"""Lazy per-tool Python processes and host-owned Vue compiler invocations."""

import asyncio
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
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


def free_port():
    with socket.socket() as handle:
        handle.bind(('127.0.0.1', 0))
        return handle.getsockname()[1]


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


def command(*args):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--tool-worker', *args]
    return [sys.executable, '-m', 'backend.tool_worker', *args]


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
            item = {'code': 'VITE', 'message': 'Vue 编译失败，请检查此处语法或导入'}
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
        diagnostic = {'code': 'SOURCE', 'message': 'Working source is incomplete or invalid. Check tool.json and the required frontend/App.vue and backend/main.py files.'}
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
    process: subprocess.Popen
    port: int
    token: str
    output: object
    host_token: str = ''
    log_run: object = None
    frontend: subprocess.Popen | None = None
    frontend_port: int | None = None

    @property
    def url(self):
        return f'http://127.0.0.1:{self.frontend_port or self.port}/api/sdk/session?session={self.token}'

    async def stop(self):
        # Caller checks active jobs first. Process termination is not safe job cancellation.
        for process, group in ((self.frontend, True), (self.process, False)):
            if process:
                await asyncio.to_thread(stop, process, group=group)
        if self.log_run:
            self.log_run.close()
        directory = os.environ.get('CALABASH_SELECTION_DIR')
        if directory:
            (Path(directory) / f'active-jobs-{self.root.name}.json').unlink(missing_ok=True)
        if self.root.parent == app_dir() / 'runtime' and not self.root.is_symlink():
            await asyncio.to_thread(shutil.rmtree, self.root, ignore_errors=True)
        (app_dir() / 'worker-config' / (self.root.name + '.json')).unlink(missing_ok=True)


class ToolWorkers:
    def __init__(self):
        self.items = {}
        self.failures = {}
        self.lock = asyncio.Lock()
        self.start_locks = {}
        self.detached = set()
        self.stopping = False

    def current(self, project, name, chat_id=None):
        key = self.key(project, name, chat_id)
        return self.items.get(key) or self.failures.get(key)

    def key(self, project, name, chat_id=None):
        return (project, name, chat_id)

    def is_open(self, project, name):
        return any((item.project, item.name) == (project, name) and item.process.poll() is None for item in self.items.values())

    async def running(self, project, name):
        for item in tuple(self.items.values()):
            if (item.project, item.name) == (project, name) and item.process.poll() is None and (await self.status(item)).get('running'):
                return True
        return False

    @asynccontextmanager
    async def publication(self, project, name):
        async with self.lock:
            locked = []
            async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
                try:
                    for item in tuple(self.items.values()):
                        if (item.project, item.name) == (project, name) and item.process.poll() is None:
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
                if previous.process.poll() is None and (not previous.frontend or previous.frontend.poll() is None):
                    return previous
                if previous.process.poll() is None and (await self._prepare_exit(previous)).get('running'):
                    raise ValueError(t('工具界面已断开，请等待当前任务完成后重新打开'))
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
                frontend_root = bundles.directory(project, name, chat_id) if chat_id else root
                # Backend modules are a read-only execution cache, never an
                # authoring directory. Lazy imports must not mix edited code
                # into an already running job before the user refreshes.
                for relative, content in source['files'].items():
                    if chat_id and not relative.startswith('backend/'):
                        continue
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
                    if relative.startswith('backend/'):
                        path.chmod(0o400)
                from service.tools.api_contracts import prepare
                prepare(root, source['files'])
                node, script = frontend_runtime()
                if not chat_id:
                    published_dist = bundles.directory(project, name) / 'dist'
                    if not (published_dist / 'index.html').is_file():
                        raise ValueError('Publish a built tool before opening')
                    shutil.copytree(published_dist, root / 'dist')
                port = free_port(); token = secrets.token_urlsafe(32); host_token = secrets.token_urlsafe(32)
                frontend_port = free_port() if chat_id else None
                origin = f'http://127.0.0.1:{frontend_port or port}'
                config = {'root': str(root), 'source_root': str(root), 'project': project, 'name': name, 'port': port,
                          'token': token, 'origin': origin, 'revision': source['revision'], 'host_token': host_token,
                          'partitioned_session': os.environ.get('CALABASH_HARNESS_EMBEDDED') == '1'}
                configs = app_dir() / 'worker-config'
                configs.mkdir(parents=True, exist_ok=True, mode=0o700)
                path = configs / (root.name + '.json'); path.write_text(json.dumps(config)); path.chmod(0o600)
                from core import tool_run_logs
                log_run = tool_run_logs.start(project, name, preview_key=chat_id)
                environment = {**os.environ, 'CALABASH_JOB_ID': root.name}
                process = await spawn(command(str(path)), cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                worker = Worker(project, name, source['revision'], root, process, port, token, None, host_token=host_token, log_run=log_run, frontend_port=frontend_port)
            except BaseException:
                if log_run:
                    log_run.close()
                await asyncio.to_thread(shutil.rmtree, root, ignore_errors=True)
                (app_dir() / 'worker-config' / (root.name + '.json')).unlink(missing_ok=True)
                raise
            def capture(stream):
                try:
                    while data := stream.read1(4096):
                        log_run.writer.write(data.decode('utf-8', errors='replace'))
                finally:
                    stream.close()
            try:
                threading.Thread(target=capture, args=(process.stdout,), daemon=True).start()
                if chat_id:
                    worker.frontend = await spawn([node, str(script), 'serve', str(root), str(port), str(frontend_port), str(frontend_root)], group=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                    threading.Thread(target=capture, args=(worker.frontend.stdout,), daemon=True).start()
                async with httpx.AsyncClient(trust_env=False) as client:
                    for _ in range(200):
                        if process.poll() is not None or worker.frontend and worker.frontend.poll() is not None:
                            raise ValueError('Tool process failed; inspect this run logs')
                        try:
                            response = await client.get(f'http://127.0.0.1:{port}/health', timeout=.5)
                            frontend_ready = not chat_id or (await client.get(origin, timeout=.5)).status_code == 200
                            if response.status_code == 200 and frontend_ready:
                                break
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(.1)
                    else:
                        raise ValueError('Tool startup timed out')
            except BaseException:
                await worker.stop()
                self.failures[key] = worker
                raise
            self.items[key] = worker
            self.failures.pop(key, None)
            return worker

    async def status(self, worker):
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.get(f'http://127.0.0.1:{worker.port}/api/sdk/status', headers={'Authorization': 'Bearer ' + worker.token})
            response.raise_for_status()
            return response.json()

    async def close(self, project, name, chat_id=None):
        key = self.key(project, name, chat_id)
        async with self.start_locks.setdefault(key, asyncio.Lock()):
            await self._close(project, name, chat_id)

    async def _close(self, project, name, chat_id=None):
        key = self.key(project, name, chat_id)
        worker = self.items.get(key)
        if worker:
            state = await self._prepare_exit(worker) if worker.process.poll() is None else {'running': False}
            if state.get('running'):
                async with httpx.AsyncClient(trust_env=False) as client:
                    await client.post(f'http://127.0.0.1:{worker.port}/api/sdk/cancel', headers={'Authorization': 'Bearer ' + worker.token})
                raise ValueError('Safe stop requested; wait for current item to finish before closing')
            await worker.stop()
            self.items.pop(key, None)
            self.detached.discard(key)

    async def detach(self, project, name, chat_id):
        key = self.key(project, name, chat_id)
        worker = self.items.get(key)
        self.detached.add(key)
        if worker and worker.process.poll() is None and (await self.status(worker)).get('running'):
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
            await worker.stop()
            self.items.pop(key, None)

    async def _prepare_exit(self, worker):
        async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
            response = await client.post(
                f'http://127.0.0.1:{worker.port}/api/sdk/prepare-exit',
                headers={'Authorization': 'Bearer ' + worker.token, 'X-Calabash-Host': worker.host_token})
            response.raise_for_status()
            return response.json()

    async def prepare_exit(self):
        self.stopping = True
        for lock in tuple(self.start_locks.values()):
            async with lock:
                pass
        ready = True
        for worker in tuple(self.items.values()):
            if worker.process.poll() is None and (await self._prepare_exit(worker)).get('running'):
                ready = False
        return ready

    async def monitor(self):
        while True:
            import time

            from service.tools import bundle_debug
            for chat_id, grant in tuple(bundle_debug.repair_grants.items()):
                if time.monotonic() - grant['time'] > 600:
                    bundle_debug.release_logs(chat_id)
            for chat_id, grant in tuple(bundle_debug.grants.items()):
                if time.monotonic() - grant['time'] > 600 or grant['worker'].process.poll() is not None:
                    bundle_debug.grants.pop(chat_id, None)
            for key, item in tuple(self.items.items()):
                broken = item.process.poll() is not None or (item.frontend and item.frontend.poll() is not None)
                if broken:
                    self.detached.add(key)
            for key in tuple(self.detached):
                item = self.items.get(key)
                try:
                    if item and (item.process.poll() is not None or not (await self.status(item)).get('running')) and key in self.detached:
                        await self.close(*key)
                except (httpx.HTTPError, ValueError):
                    continue  # Unknown state must not terminate a possible writer.
            directory = os.environ.get('CALABASH_SELECTION_DIR')
            if directory:
                for worker in tuple(self.items.values()):
                    if worker.process.poll() is not None:
                        (Path(directory) / f'active-jobs-{worker.root.name}.json').unlink(missing_ok=True)
            await asyncio.sleep(.2)


workers = ToolWorkers()
