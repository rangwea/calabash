"""Vue host HTTP application; no server-side UI framework."""

import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.workspace_api import router
from service.chat.chat_runs import runs

DIST = Path(__file__).resolve().parents[1] / 'desktop-ui/dist'


def create_workspace_app():
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        import asyncio

        from service.tools.tool_workers import workers
        from service.tools.tool_checks import checks
        from service.tools.exit_handshake import watch
        workers.stopping = False
        monitor = asyncio.create_task(workers.monitor())
        exit_task = asyncio.create_task(watch(workers, checks, runs))
        try:
            yield
        finally:
            exit_task.cancel()
            await asyncio.gather(exit_task, return_exceptions=True)
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
            from service.tools.tool_checks import checks
            await checks.close()
            await runs.close()
            await workers.shutdown()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.middleware('http')
    async def local_session(request: Request, call_next):
        if request.url.hostname not in {'127.0.0.1', 'localhost', 'testserver'}:
            return JSONResponse({'detail': 'Invalid host'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': 'Foreign origin'}, status_code=403)
        if request.headers.get('sec-fetch-site') in {'cross-site', 'same-site'}:
            return JSONResponse({'detail': 'Foreign request'}, status_code=403)
        if request.url.path.startswith('/api/'):
            from service.tools.tool_workers import workers
            if workers.stopping and request.method not in {'GET', 'HEAD'}:
                from core.i18n import t
                return JSONResponse({'detail': t('应用正在安全退出，暂不接受新任务')}, status_code=409)
            if request.cookies.get('calabash-session') != token:
                return JSONResponse({'detail': 'Session unavailable'}, status_code=403)
            if request.method not in {'GET', 'HEAD'} and request.headers.get('x-calabash-request') != 'workspace':
                return JSONResponse({'detail': 'Request marker required'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        if not request.url.path.startswith('/api/'):
            response.set_cookie('calabash-session', token, httponly=True, samesite='strict')
        return response

    app.include_router(router)
    from api.bundle_api import router as bundles
    app.include_router(bundles)

    @app.get('/preview/{project}/{name}')
    async def preview(project: str, name: str, chat: str):
        from service.tools import tool_bundles
        from service.tools.tool_workers import workers
        if not ai_chat_exists(chat):
            return JSONResponse({'detail': 'Conversation unavailable'}, status_code=404)
        source = tool_bundles.read(project, name, chat)
        from service.tools.tool_checks import checks
        checks.ensure(project, name, chat, source)
        worker = workers.items.get(workers.key(project, name, chat))
        if worker and worker.revision != source['revision']:
            await workers.close(project, name, chat)
        worker = await workers.open(project, name, chat)
        return RedirectResponse(worker.url)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        from core.logger import get_logger
        get_logger(__name__).opt(exception=error).warning('Workspace action rejected: {} {}', request.method, request.url.path)
        return JSONResponse({'detail': str(error)}, status_code=409)

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    if (DIST / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets')

    @app.get('/{path:path}')
    def index(path: str):
        if path.startswith('api/'):
            return JSONResponse({'detail': 'Not found'}, status_code=404)
        if not (DIST / 'index.html').is_file():
            return JSONResponse({'detail': 'Build desktop UI first: npm run desktop:web:build'}, status_code=503)
        return FileResponse(DIST / 'index.html')

    return app


def ai_chat_exists(chat):
    from service.chat.ai_chat import chat_exists
    return chat_exists(chat)
