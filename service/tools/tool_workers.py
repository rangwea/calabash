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

from core.local_paths import app_dir
from service.tools import tool_bundles as bundles

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
    for match in re.finditer(r'(frontend/[a-zA-Z0-9_./-]+)\((\d+),(\d+)\): error (TS\d+):', output):
        path, line, column, code = match.groups()
        try:
            bundles.safe_path(path)
        except ValueError:
            continue
        message = {'TS2322': '组件值类型不匹配，请处理空值或联合类型',
                   'TS2353': '组件不支持此属性或事件，请查询组件接口',
                   'TS2339': '属性不存在，请检查对象或组件接口',
                   'TS2307': '无法解析模块，请使用内置库或正确的相对路径'}.get(code, 'TypeScript 检查失败，请检查此处代码')
        item = {'file': path, 'line': int(line), 'column': int(column), 'code': code, 'message': message}
        if item not in result:
            result.append(item)
        if len(result) >= 20:
            break
    diagnostic = root / 'build-diagnostics.json'
    if not result and diagnostic.is_file() and not diagnostic.is_symlink() and diagnostic.stat().st_size < 8192:
        try:
            value = json.loads(diagnostic.read_text())
            item = {'code': 'VITE', 'message': 'Vue 编译失败，请检查此处语法或导入'}
            if value.get('code') == 'API_CONTRACT':
                item = {'code': 'API_CONTRACT', 'message': str(value.get('message', '接口契约检查失败'))[:300]}
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
    bundles.validate(files)
    root = app_dir() / 'builds' / uuid4().hex
    root.mkdir(parents=True, mode=0o700)
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
        process = await asyncio.create_subprocess_exec(node, str(script), 'build', str(root), stdout=output, stderr=output)
        try:
            await asyncio.wait_for(process.wait(), 90)
        except BaseException as error:
            if process.returncode is None:
                process.kill()
                await process.wait()
            if isinstance(error, asyncio.CancelledError):
                shutil.rmtree(root, ignore_errors=True)
            if isinstance(error, TimeoutError):
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
        for process in (self.frontend, self.process):
            if process and process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait)
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
        key = self.key(project, name, chat_id)
        async with self.start_locks.setdefault(key, asyncio.Lock()):
            self.detached.discard(key)
            if key in self.items and self.items[key].process.poll() is None:
                return self.items[key]
            source = bundles.read(project, name, chat_id)
            meta = bundles.validate(source['files'])
            from service.capabilities.tool_capabilities import require_tool_capabilities
            requirements = meta.get('requires', '')
            require_tool_capabilities(requirements)
            root = app_dir() / 'runtime' / uuid4().hex
            root.mkdir(parents=True, mode=0o700)
            for relative, content in source['files'].items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
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
            config = {'root': str(root), 'project': project, 'name': name, 'port': port,
                      'token': token, 'origin': origin, 'revision': source['revision'], 'host_token': host_token}
            configs = app_dir() / 'worker-config'
            configs.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = configs / (root.name + '.json'); path.write_text(json.dumps(config)); path.chmod(0o600)
            from core import tool_run_logs
            log_run = tool_run_logs.start(project, name, preview_key=chat_id)
            environment = {**os.environ, 'CALABASH_JOB_ID': root.name}
            process = await asyncio.to_thread(subprocess.Popen, command(str(path)), cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            worker = Worker(project, name, source['revision'], root, process, port, token, None, host_token=host_token, log_run=log_run, frontend_port=frontend_port)
            def capture(stream):
                try:
                    while data := stream.read1(4096):
                        log_run.writer.write(data.decode('utf-8', errors='replace'))
                finally:
                    stream.close()
            threading.Thread(target=capture, args=(process.stdout,), daemon=True).start()
            try:
                if chat_id:
                    worker.frontend = await asyncio.to_thread(subprocess.Popen, [node, str(script), 'serve', str(root), str(port), str(frontend_port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
        worker = self.items.get(key)
        if worker:
            state = await self.status(worker) if worker.process.poll() is None else {'running': False}
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
        for worker in list(self.items.values()):
            await worker.stop()
        self.items.clear()

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
            for key in tuple(self.detached):
                item = self.items.get(key)
                try:
                    if item and (item.process.poll() is not None or not (await self.status(item)).get('running')) and key in self.detached:
                        await self.close(*key)
                except httpx.HTTPError:
                    continue  # Unknown state must not terminate a possible writer.
            directory = os.environ.get('CALABASH_SELECTION_DIR')
            if directory:
                for worker in tuple(self.items.values()):
                    if worker.process.poll() is not None:
                        (Path(directory) / f'active-jobs-{worker.root.name}.json').unlink(missing_ok=True)
            await asyncio.sleep(.2)


workers = ToolWorkers()
