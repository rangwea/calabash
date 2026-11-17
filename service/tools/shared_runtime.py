"""One ASGI gateway, loopback origins and no tool subprocesses."""
import asyncio
import socket
import sys
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI
from starlette.responses import PlainTextResponse


class Listener(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # The owning stdio runtime drains all tools on EOF/SIGINT.
        yield


class SharedRuntime(FastAPI):
    def __init__(self):
        super().__init__(docs_url=None, redoc_url=None, openapi_url=None)
        self.instances = {}

    async def __call__(self, scope, receive, send):
        port = scope.get('server', ('', 0))[1]
        instance = self.instances.get(port)
        if instance is None:
            await PlainTextResponse('Tool unavailable', status_code=404)(scope, receive, send)
            return
        business = scope.get('path', '').startswith('/api/') and not scope['path'].startswith('/api/sdk/')
        if business and instance.sdk._stopping:
            await PlainTextResponse('Tool is stopping', status_code=409)(scope, receive, send)
            return
        if business and instance.sdk._publishing:
            await PlainTextResponse('Tool is being saved', status_code=409)(scope, receive, send)
            return
        instance.active_calls += int(business)
        try:
            with instance.log_run.context():
                await instance.app(scope, receive, send)
        finally:
            instance.active_calls -= int(business)

    async def listen(self, instance, sock):
        self.instances[instance.port] = instance
        config = uvicorn.Config(self, host='127.0.0.1', port=instance.port, lifespan='off', access_log=False,
                                log_config=None, timeout_keep_alive=1)
        server = Listener(config)
        task = asyncio.create_task(server.serve(sockets=[sock]))
        instance.server, instance.server_task = server, task
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        raise ValueError('Tool listener could not start')
                    await asyncio.sleep(.01)
        except BaseException:
            server.should_exit = True
            await asyncio.gather(task, return_exceptions=True)
            self.instances.pop(instance.port, None)
            sock.close()
            raise

    async def remove(self, instance):
        if instance.server:
            instance.server.should_exit = True
            await asyncio.gather(instance.server_task, return_exceptions=True)
        self.instances.pop(instance.port, None)


def socket_for_origin():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    sock.setblocking(False)
    return sock


def unload(namespace):
    for name in tuple(sys.modules):
        if name == namespace or name.startswith(namespace + '.'):
            sys.modules.pop(name, None)
