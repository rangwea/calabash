"""Independent tool HTTP process. Tool modules register routes using setup()."""

import asyncio
import hashlib
import importlib.util
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles


def create_tool_app(config):
    from service.tools.tool_sdk import ToolSDK
    root = Path(config['root'])
    sdk = ToolSDK(config['project'], config['name'])
    sdk.host_token = config.get('host_token', '')
    @asynccontextmanager
    async def lifespan(app):
        sdk.loop = asyncio.get_running_loop()
        yield
        await sdk.shutdown()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    from service.tools.api_errors import failure, install
    install(app, root)

    @app.middleware('http')
    async def authorize(request: Request, call_next):
        if request.url.hostname != '127.0.0.1':
            return JSONResponse({'detail': 'Invalid host'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != config['origin']:
            return JSONResponse({'detail': 'Foreign origin'}, status_code=403)
        cookie = 'calabash-tool-' + str(config['port'])
        token = request.cookies.get(cookie) or request.headers.get('authorization', '').removeprefix('Bearer ')
        bootstrap = request.url.path == '/api/sdk/session' and request.query_params.get('session') == config['token']
        navigation = request.url.path == '/' and request.method == 'GET' and token == config['token']
        if request.headers.get('sec-fetch-site') in {'cross-site', 'same-site'} and not (bootstrap or navigation):
            return JSONResponse({'detail': 'Foreign request'}, status_code=403)
        if request.url.path != '/health' and not bootstrap and token != config['token']:
            return JSONResponse({'detail': 'Session unavailable'}, status_code=403)
        from uuid import uuid4
        request.state.api_request_id = uuid4().hex
        try:
            response = await call_next(request)
        except Exception as error:  # noqa: BLE001 - isolate arbitrary user-tool failures at the HTTP boundary.
            response = failure(request, error, root)
        if bootstrap:
            response.set_cookie(cookie, config['token'], httponly=True, samesite='strict')
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/health')
    def health():
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

    source = root / 'backend/main.py'
    sys.path.insert(0, str(source.parent))
    module_name = 'calabash_user_tool_' + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(module_name, source)
    module = importlib.util.module_from_spec(spec)
    # Pydantic resolves postponed annotations through the defining module.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    module.setup(app, sdk)
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


def main():
    config = json.loads(Path(sys.argv[-1]).read_text())
    uvicorn.run(create_tool_app(config), host='127.0.0.1', port=config['port'], access_log=False, log_config=None)


if __name__ == '__main__':
    main()
