"""Isolated tool ASGI application factory hosted by the shared runtime."""

import asyncio
import hashlib
import importlib.util
import json
import secrets
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles


def create_tool_app(config):
    sys.dont_write_bytecode = True
    from service.tools.tool_sdk import ToolSDK
    root = Path(config['root'])
    source_root = Path(config.get('source_root', root))
    sdk = ToolSDK(config['project'], config['name'], run_id=root.name, source_revision=config.get('revision', ''))
    sdk.host_token = config.get('host_token', '')
    from service.tools.preview_diagnostics import PreviewDiagnostics
    sdk.diagnostics = PreviewDiagnostics(config['project'], config['name'], config.get('diagnostic_owner', 'published'), root.name, config.get('revision', ''))
    @asynccontextmanager
    async def lifespan(app):
        sdk.loop = asyncio.get_running_loop()
        yield
        await sdk.shutdown()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    from service.tools.api_errors import failure, install
    install(app, source_root, sdk.diagnostics)

    @app.middleware('http')
    async def authorize(request: Request, call_next):
        if request.url.hostname != '127.0.0.1':
            return JSONResponse({'detail': 'Invalid host'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != config['origin']:
            return JSONResponse({'detail': 'Foreign origin'}, status_code=403)
        cookie = 'calabash-tool-' + str(config['port'])
        token = request.cookies.get(cookie) or request.headers.get('authorization', '').removeprefix('Bearer ')
        bootstrap = request.url.path == '/api/sdk/session' and secrets.compare_digest(request.query_params.get('session') or '', config['token'])
        navigation = request.url.path == '/' and request.method == 'GET' and secrets.compare_digest(token, config['token'])
        if request.headers.get('sec-fetch-site') in {'cross-site', 'same-site'} and not (bootstrap or navigation):
            return JSONResponse({'detail': 'Foreign request'}, status_code=403)
        if request.url.path != '/health' and not bootstrap and not secrets.compare_digest(token, config['token']):
            return JSONResponse({'detail': 'Session unavailable'}, status_code=403)
        from uuid import uuid4
        request.state.api_request_id = uuid4().hex
        try:
            response = await call_next(request)
        except Exception as error:  # noqa: BLE001 - isolate arbitrary user-tool failures at the HTTP boundary.
            response = failure(request, error, source_root, sdk.diagnostics)
        if bootstrap:
            if config.get('partitioned_session'):
                # Electron's dsh-app top-level origin is cross-site to the tool.
                # CHIPS keeps this cookie scoped to that embedding site; no CORS
                # or native permissions are granted to the tool frame.
                response.headers.append('Set-Cookie', f"{cookie}={config['token']}; Path=/; HttpOnly; Secure; SameSite=None; Partitioned")
            else:
                response.set_cookie(cookie, config['token'], httponly=True, samesite='strict')
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/health')
    async def health():
        return {'status': 'ok'}

    app.include_router(sdk.router, prefix='/api/sdk')

    @app.get('/api/sdk/session')
    def session():
        return RedirectResponse('/')
    @app.get('/api/sdk/runtime-guard.js')
    def runtime_guard():
        from core.i18n import language
        from service.tools.tool_workers import frontend_runtime
        script = frontend_runtime()[1].with_name('tool_runtime_guard.js')
        return Response('const guardLanguage = ' + json.dumps(language()) + ';\n' + script.read_text(encoding='utf-8'), media_type='text/javascript', headers={'Cache-Control': 'no-store'})

    source = source_root / 'backend/main.py'
    namespace = 'calabash_user_tool_' + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    for package_name, package_path in ((namespace, source_root), (namespace + '.backend', source.parent)):
        package = types.ModuleType(package_name)
        package.__path__ = [str(package_path)]
        sys.modules[package_name] = package
    module_name = namespace + '.backend.main'
    spec = importlib.util.spec_from_file_location(module_name, source)
    module = importlib.util.module_from_spec(spec)
    # Pydantic resolves postponed annotations through the defining module.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        module.setup(app, sdk)
    except BaseException:
        for loaded in tuple(sys.modules):
            if loaded == namespace or loaded.startswith(namespace + '.'):
                sys.modules.pop(loaded, None)
        raise
    app.state.sdk = sdk
    app.state.namespace = namespace
    files = {path.relative_to(source_root).as_posix(): path.read_text(encoding='utf-8') for path in (source_root / 'backend').rglob('*.py') if not path.is_symlink()}
    sdk.diagnostics.check_interfaces(app, files)
    if (root / 'dist/assets').is_dir():
        app.mount('/assets', StaticFiles(directory=root / 'dist/assets'))

    @app.get('/')
    def index():
        if not (root / 'dist/index.html').is_file():
            return JSONResponse({'detail': 'Frontend is served by preview compiler'}, status_code=404)
        html = (root / 'dist/index.html').read_text(encoding='utf-8')
        if '/api/sdk/runtime-guard.js' not in html:
            tag = '<script src="/api/sdk/runtime-guard.js"></script>'
            html = html.replace('<head>', '<head>' + tag, 1) if '<head>' in html else tag + html
        return HTMLResponse(html)

    return app
