"""Friendly tool API errors and value-free diagnostics in the current run log."""

import json
import logging
import traceback
from pathlib import Path
from typing import get_args
from uuid import uuid4

from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from core.i18n import t


def field_names(route):
    """Only schema-declared names can appear in validation diagnostics."""
    names = {'body', 'query', 'path', 'response'}
    dependent = getattr(route, 'dependant', None)
    pending = [getattr(route, 'response_model', None)]
    for kind in ('body_params', 'query_params', 'path_params'):
        for field in getattr(dependent, kind, ()):
            names.add(field.name)
            pending.append(field.field_info.annotation)
    seen = set()
    while pending and len(seen) < 100:
        model = pending.pop()
        if id(model) in seen:
            continue
        seen.add(id(model))
        pending.extend(get_args(model))
        if isinstance(model, type) and issubclass(model, BaseModel):
            for name, field in model.model_fields.items():
                names.add(name)
                pending.append(field.annotation)
    return names


def failure(request, error, root):
    route = request.scope.get('route')
    request_id = getattr(request.state, 'api_request_id', None) or uuid4().hex
    status = 500
    code = 'operation_failed'
    message = t('工具暂时未能完成操作，请重试或让 AI 帮你修复')
    details = []
    allowed_fields = field_names(route)
    if isinstance(error, (RequestValidationError, ResponseValidationError)):
        is_input = isinstance(error, RequestValidationError)
        status = 422 if is_input else 500
        code = 'request_validation_failed' if is_input else 'response_validation_failed'
        if is_input:
            message = t('请检查填写的内容或所选文件后重试')
        for item in error.errors()[:20]:
            # Pydantic errors also contain input values and validator context.
            # Keep only field locations and machine-readable error kinds.
            location = [part if type(part) is int or isinstance(part, str) and part in allowed_fields else '<field>'
                        for part in item.get('loc', ())]
            details.append({'location': location[:8], 'kind': str(item.get('type', 'invalid'))[:80]})
    elif isinstance(error, HTTPException):
        status = error.status_code
        code = {404: 'not_found', 409: 'conflict'}.get(status, 'invalid_request' if status < 500 else 'operation_failed')
        if status < 500:
            message = t('请检查填写的内容或所选文件后重试')
    frames = []
    for frame in traceback.extract_tb(error.__traceback__):
        try:
            path = Path(frame.filename).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        if path.startswith('backend/'):
            frames.append({'file': path, 'line': frame.lineno, 'function': frame.name})
    record = {'request_id': request_id, 'method': request.method,
              'route': getattr(route, 'path', '<unmatched>'),
              'operation': getattr(route, 'operation_id', None), 'code': code,
              'exception': type(error).__name__, 'fields': details, 'frames': frames[-12:]}
    logging.getLogger(__name__).error('Tool API diagnostic %s', json.dumps(record, ensure_ascii=False))
    return JSONResponse({'error': {'code': code, 'message': message, 'request_id': request_id}},
                        status_code=status, headers={'X-Calabash-Request-Id': request_id})


def install(app, root):
    async def handle(request, error):
        return failure(request, error, root)
    for kind in (RequestValidationError, ResponseValidationError, HTTPException):
        app.add_exception_handler(kind, handle)
