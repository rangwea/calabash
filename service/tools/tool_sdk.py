"""Small Python tool SDK with cooperative jobs and owned persistent data."""

import asyncio
import json
import secrets
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from core.local_paths import app_dir
from service.actions.models import ActionRequest
from service.tools.tool_database import ToolDatabase
from service.tools.tool_jobs import ToolJobs


class ToolSDK:
    def __init__(self, project, name, *, run_id=None, source_revision=""):
        from service.tools.tool_bundles import identity
        self.project, self.name = identity(project), identity(name)
        self.owner = f'tool:{project}/{name}'
        self.run_id = run_id or uuid4().hex
        self.source_revision = source_revision
        self.data_dir = app_dir() / 'tools' / project / name
        self._database = ToolDatabase(self.data_dir)
        self.jobs = None
        self.task = None
        self.loop = None
        self._start_lock = Lock()
        self._cancel_pending = False
        self._publishing = False
        self._stopping = False
        self.host_token = ''
        self.router = APIRouter()
        self.router.add_api_route('/runtime-issue', self.runtime_issue, methods=['POST'])
        self.router.add_api_route('/verification', self.verification, methods=['GET'])
        self.router.add_api_route('/verification', self.verification_evidence, methods=['POST'])
        self.router.add_api_route('/page-evidence', self.page_evidence, methods=['POST'])
        self.router.add_api_route('/prepare-exit', self.prepare_exit, methods=['POST'])
        self.router.add_api_route('/status', self.status, methods=['GET'])
        self.router.add_api_route('/cancel', self.cancel, methods=['POST'])
        self.router.add_api_route('/publication-lock', self.publication_lock, methods=['POST'])
        self.router.add_api_route('/results', self.results, methods=['GET'])
        self.router.add_api_route('/results/{file_id}', self.result, methods=['GET'])
        self.router.add_api_route('/inputs', self.inputs, methods=['GET'])
        self.router.add_api_route('/inputs', self.upload_input, methods=['POST'])
        self.router.add_api_route('/inputs/{file_id}', self.remove_input, methods=['DELETE'])
        self.router.add_api_route('/inputs/{file_id}/content', self.input_content, methods=['GET'])
        self.router.add_api_route('/native-inputs', self.native_inputs, methods=['POST'])
        self.router.add_api_route('/debug/next', self.debug_next, methods=['GET'])
        self.router.add_api_route('/debug/result', self.debug_result, methods=['POST'])
        self.router.add_api_route('/debug/request', self.debug_request, methods=['POST'])
        from service.actions.runtime import ToolActions
        self.actions = ToolActions(self)
        from service.actions.ai import ToolAI
        self.ai = ToolAI(self)
        self.router.add_api_route('/ai/requests', self.ai.pending, methods=['GET'])
        self.router.add_api_route('/ai/control', self.ai.control, methods=['POST'])
        self.router.add_api_route('/actions', self.action_catalog, methods=['GET'])
        self.router.add_api_route('/actions/{action_id}', self.action_schema, methods=['GET'])
        self.router.add_api_route('/actions/{action_id}', self.start_action, methods=['POST'])
        self.router.add_api_route('/action-runs', self.actions.runs, methods=['GET'])
        self.commands = asyncio.Queue(maxsize=20)
        self.pending = {}
        from service.files.tool_outputs import ToolOutputs
        self.outputs = ToolOutputs(owner=(self.owner, None))
        self._inputs = {}

    def action_catalog(self):
        from service.actions.registry import catalog
        return catalog()

    def action_schema(self, action_id: str):
        from service.actions.errors import ActionFailure
        from service.actions.registry import describe
        try:
            return describe(action_id)
        except ActionFailure:
            raise HTTPException(404, 'Action unavailable') from None

    async def start_action(self, action_id: str, request: ActionRequest):
        return await self.actions.submit(action_id, request)

    async def verification(self, request: Request):
        self.host_request(request)
        value = getattr(self, 'diagnostics', None)
        return value.report() if value else {'page': 'unavailable', 'diagnostics': []}

    async def verification_evidence(self, request: Request):
        self.host_request(request)
        content = await request.body()
        if len(content) > 2048:
            raise HTTPException(400, 'Invalid verification record')
        try:
            value = json.loads(content)
            if not isinstance(value, dict) or value.get('code') != 'MODULE_HTTP':
                raise ValueError('Invalid verification record')
            self.diagnostics.event(value)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Invalid verification record') from None
        return {'ok': True}

    async def page_evidence(self, request: Request):
        content = await request.body()
        if len(content) > 2048:
            raise HTTPException(400, 'Invalid page evidence')
        try:
            value = json.loads(content)
            if not isinstance(value, dict) or value.get('code') not in {'PAGE_READY', 'PAGE_EMPTY', 'PAGE_SCRIPT', 'PAGE_RESOURCE'}:
                raise ValueError('Invalid page evidence')
            if getattr(self, 'diagnostics', None):
                self.diagnostics.event(value)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Invalid page evidence') from None
        return {'ok': True}

    async def runtime_issue(self, request: Request):
        from core.logger import get_logger
        content = await request.body()
        if len(content) > 2048:
            raise HTTPException(400, 'Invalid issue record')
        try:
            value = json.loads(content)
        except ValueError:
            raise HTTPException(400, 'Invalid issue record') from None
        if not isinstance(value, dict) or value.get('kind') not in {'request_failed', 'connection_failed', 'javascript_error', 'unhandled_rejection'}:
            raise HTTPException(400, 'Invalid issue record')
        status = value.get('status', 0)
        if type(status) is not int or not 0 <= status <= 599:
            raise HTTPException(400, 'Invalid issue record')
        request_id = value.get('request_id', '')
        import re
        if not isinstance(request_id, str) or request_id and not re.fullmatch(r'[a-f0-9]{32}', request_id):
            raise HTTPException(400, 'Invalid issue record')
        # No request body, query, frontend message or browser stack is accepted.
        get_logger(__name__).error('Tool browser issue: kind={} status={} request_id={}', value['kind'], status, request_id)
        return {'ok': True}

    def status(self):
        return {'running': bool(self.task and not self.task.done()),
                'status': self.jobs.status if self.jobs else 'idle',
                'progress': self.jobs.progress if self.jobs else 0,
                'counts': self.jobs.counts if self.jobs else {}}

    def cancel(self):
        self._cancel_pending = True
        if self.loop:
            self.loop.call_soon_threadsafe(self.ai.cancel)
        if self.jobs:
            self.jobs.cancel()
        return self.status()

    def start_batch(self, values, handler):
        with self._start_lock:
            if self._stopping:
                from core.i18n import t
                raise HTTPException(409, t('应用正在安全退出，暂不接受新任务'))
            if self._publishing:
                raise HTTPException(409, 'A tool version is being saved')
            if self.task and not self.task.done():
                raise HTTPException(409, 'A task is already running')
            try:
                current = asyncio.get_running_loop()
            except RuntimeError:
                current = None
            self.loop = self.loop or current
            if not self.loop:
                raise HTTPException(503, 'Tool runtime is not ready')
            self.jobs = ToolJobs(values, owner=self.owner)
            self._cancel_pending = False
            async def execute():
                try:
                    if self._cancel_pending:
                        self.jobs.status = 'cancelled'
                        for job in self.jobs.jobs:
                            job.status = 'cancelled'
                        return
                    await self.jobs.run(handler)
                finally:
                    self.actions.release_ai_inputs()
            self.task = self.loop.create_task(execute()) if self.loop is current else asyncio.run_coroutine_threadsafe(execute(), self.loop)
        return self.status()

    def host_request(self, request):
        if not self.host_token or not secrets.compare_digest(request.headers.get('x-calabash-host', ''), self.host_token):
            raise HTTPException(403, 'Host authorization required')

    def publication_lock(self, frozen: bool, request: Request):
        self.host_request(request)
        with self._start_lock:
            if frozen and self.task and not self.task.done():
                raise HTTPException(409, 'Tool is running')
            self._publishing = frozen
        return {'ok': True}

    def prepare_exit(self, request: Request):
        self.host_request(request)
        with self._start_lock:
            self._stopping = True
            return self.cancel()

    async def shutdown(self):
        if self.task and not self.task.done():
            self.cancel()
            task = self.task if isinstance(self.task, asyncio.Future) else asyncio.wrap_future(self.task)
            await asyncio.shield(task)

    async def io(self, function, *args, **kwargs):
        return await asyncio.to_thread(function, *args, **kwargs)

    def database(self, *, write=False):
        return self._database.transaction(write=write)

    def get_setting(self, key, default=None):
        return self._database.get_setting(key, default)

    def set_setting(self, key, value):
        self._database.set_setting(key, value)

    def output_path(self, name):
        name = Path(name).name
        root = self.data_dir / 'outputs' / uuid4().hex
        root.mkdir(parents=True)
        return root / name

    def add_result(self, path):
        path = Path(path)
        if path.is_symlink() or not path.resolve().is_relative_to(self.data_dir.resolve() / 'outputs') or not path.is_file():
            raise ValueError('Result must be a generated output')
        import shutil
        identity = self.outputs.write(path.name, lambda destination: shutil.copyfile(path, destination))
        return {'id': identity, 'name': path.name}

    def results(self):
        return self.outputs.files(limit=100)

    def result(self, file_id: str):
        try:
            path = self.outputs.path(file_id)
        except (KeyError, OSError, ValueError):
            raise HTTPException(404, 'Result unavailable')
        return FileResponse(path, filename=path.name)

    async def upload_input(self, file: UploadFile):
        if self.status()['running']:
            raise HTTPException(409, 'Inputs are frozen during execution')
        if len(self._inputs) >= 20:
            raise HTTPException(400, 'Input limit reached')
        name = (file.filename or 'file').replace('\\', '/').rsplit('/', 1)[-1]
        if name in {'', '.', '..'} or len(name) > 200:
            raise HTTPException(400, 'Invalid filename')
        folder = self.data_dir / 'inputs' / uuid4().hex
        folder.mkdir(parents=True)
        path = folder / name
        total = 0
        try:
            with path.open('xb') as output:
                while chunk := await file.read(65536):
                    total += len(chunk)
                    if total > 50 * 1024 * 1024:
                        raise HTTPException(413, 'Input too large')
                    output.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        identity = uuid4().hex
        path = path.resolve()
        info = path.stat()
        self._inputs[identity] = {'path': path, 'original': path, 'name': name, 'size': total,
                                 'signature': (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns), 'uploaded': True}
        return {'id': identity, 'name': name, 'size': total}

    def inputs(self):
        result = []
        for key, item in self._inputs.items():
            try:
                self.input_path(key)
                status = 'ready'
            except PermissionError:
                status = 'denied'
            except OSError:
                status = 'missing'
            except ValueError:
                status = 'changed'
            result.append({'id': key, 'name': item['name'], 'size': item['size'], 'status': status})
        return result

    def input_path(self, file_id):
        item = self._inputs[file_id]; path = item['path']
        info = path.stat()
        if path.is_symlink() or not path.is_file() or item['original'].resolve() != path or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != item['signature']:
            raise ValueError('Input changed or unavailable')
        return path

    def remove_input(self, file_id: str):
        if self.status()['running']:
            raise HTTPException(409, 'Inputs are frozen during execution')
        item = self._inputs.pop(file_id, None)
        if item and item.get('uploaded'):
            item['path'].unlink(missing_ok=True)
        return {'ok': True}

    async def native_inputs(self, request: Request):
        self.host_request(request)
        if self.status()['running']:
            raise HTTPException(409, 'Inputs are frozen during execution')
        body = await request.json()
        paths = body.get('paths')
        if not isinstance(paths, list) or len(paths) > 20 or len(paths) + len(self._inputs) > 20:
            raise HTTPException(400, 'Input limit reached')
        from service.files.input_snapshot import snapshot
        for selected in paths:
            original, path, info = snapshot(selected)
            signature = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if any(item['path'] == path and item['signature'] == signature for item in self._inputs.values()):
                continue
            self._inputs[uuid4().hex] = {'path': path, 'original': original, 'name': original.name,
                'size': info.st_size, 'signature': signature, 'uploaded': False}
        return self.inputs()

    def input_content(self, file_id: str):
        try:
            path = self.input_path(file_id)
        except (KeyError, OSError, ValueError):
            raise HTTPException(404, 'Input unavailable') from None
        inline = path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac', '.mp4', '.webm', '.mov'}
        return FileResponse(path, filename=path.name, content_disposition_type='inline' if inline else 'attachment',
                            headers={'Content-Security-Policy': "sandbox; default-src 'none'"})

    async def debug_next(self):
        try:
            return self.commands.get_nowait()
        except asyncio.QueueEmpty:
            return {}

    async def debug_request(self, request: Request):
        self.host_request(request)
        body = await request.json()
        if body.get('operation') not in {'snapshot', 'operate'}:
            raise HTTPException(400, 'Invalid diagnostic command')
        identity = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[identity] = future
        try:
            self.commands.put_nowait({'id': identity, **body})
            return await asyncio.wait_for(future, 8)
        finally:
            self.pending.pop(identity, None)

    async def debug_result(self, request: Request):
        if int(request.headers.get('content-length', '0')) > 50000:
            raise HTTPException(400, 'Diagnostic result too large')
        body = await request.json()
        future = self.pending.get(body.get('id'))
        if future and not future.done():
            future.set_result(body.get('result'))
        return {'ok': True}
