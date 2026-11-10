"""Ephemeral frozen AI requests. Only the host can approve/complete them."""
import asyncio
import hashlib
import json
import math
import time
from uuid import uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from service.actions.office import ActionFailure

TTL_SECONDS = 600
TASK_TITLES = {'summarize': '总结内容', 'classify': '分类内容', 'extract': '提取信息', 'translate': '翻译文本', 'generate': '生成内容'}


def validate_parameters(parameters):
    if not parameters.text.strip():
        raise ActionFailure('invalid_parameters')
    if parameters.task == 'translate' and not parameters.language.strip():
        raise ActionFailure('invalid_parameters')
    if parameters.task == 'classify' and len(parameters.labels) < 2:
        raise ActionFailure('invalid_parameters')
    if parameters.task == 'extract' and not parameters.fields:
        raise ActionFailure('invalid_parameters')
    if (parameters.task != 'classify' and parameters.labels or parameters.task != 'extract' and parameters.fields
            or parameters.task != 'translate' and parameters.language):
        raise ActionFailure('invalid_parameters')


def validated_output(parameters, text):
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > 65536 or len(text) > 32000:
        raise ActionFailure('ai_invalid_output')
    if parameters.task not in {'classify', 'extract'}:
        return text, '.txt'
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate key')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('Invalid number')
    try:
        value = json.loads(text, object_pairs_hook=object_pairs, parse_constant=constant)
        if not isinstance(value, dict):
            raise TypeError('Expected object')
        if parameters.task == 'classify':
            if set(value) != {'label'} or value['label'] not in parameters.labels:
                raise ValueError('Unknown label')
        else:
            if set(value) != set(parameters.fields):
                raise ValueError('Unexpected fields')
            for key, kind in parameters.fields.items():
                item = value[key]
                if (kind == 'string' and type(item) is not str or kind == 'boolean' and type(item) is not bool
                        or kind == 'number' and (type(item) not in (int, float) or not math.isfinite(item))):
                    raise ValueError('Wrong field type')
        return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), '.json'
    except (ValueError, TypeError, OverflowError):
        raise ActionFailure('ai_invalid_output') from None


class AIControl(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    request_id: str = Field(min_length=1, max_length=80)
    digest: str = Field(min_length=64, max_length=64)
    operation: str = Field(max_length=16)
    lease: str = Field(default='', max_length=80)
    text: str = Field(default='', max_length=32000)


class ToolAI:
    def __init__(self, sdk):
        self.sdk = sdk
        self.current = None
        self.future = None
        self.encoded = b''
        self.lease = ''
        self.state = 'idle'

    async def request(self, invocation, parameters):
        validate_parameters(parameters)
        payload = parameters.model_dump()
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        future = asyncio.get_running_loop().create_future()
        self.future = future
        self.encoded = encoded
        self.current = {'request_id': uuid4().hex, 'invocation_id': invocation, 'worker_id': self.sdk.run_id,
                        'revision': self.sdk.source_revision, 'digest': hashlib.sha256(encoded).hexdigest(),
                        'expires': time.time() + TTL_SECONDS, 'task': parameters.task, 'title': TASK_TITLES[parameters.task],
                        'characters': len(parameters.text)}
        self.state = 'pending'
        try:
            while True:
                try:
                    return await asyncio.wait_for(asyncio.shield(future), max(.01, self.current['expires'] - time.time()))
                except TimeoutError:
                    if self.current['expires'] <= time.time():
                        raise ActionFailure('ai_expired' if self.state == 'pending' else 'ai_failed') from None
        finally:
            if not future.done():
                future.cancel()
            self.current = None
            self.encoded = b''
            self.future = None
            self.lease = ''
            self.state = 'idle'

    def cancel(self):
        if self.future is not None and not self.future.done():
            self.future.cancel()

    async def pending(self, request: Request):
        self.sdk.host_request(request)
        value = self.current
        if not value or not self.future or self.future.done() or time.time() >= value['expires']:
            return []
        return [{key: item for key, item in value.items() if key != 'payload'} | {'state': self.state}]

    async def control(self, packet: AIControl, request: Request):
        self.sdk.host_request(request)
        value = self.current
        if (not value or not self.future or self.future.done() or value['request_id'] != packet.request_id
                or value['digest'] != packet.digest or hashlib.sha256(self.encoded).hexdigest() != value['digest'] or time.time() >= value['expires']):
            raise HTTPException(409, 'AI request unavailable')
        if packet.operation == 'review' and self.state == 'pending':
            return {**value, 'payload': json.loads(self.encoded)}
        if packet.operation == 'reject':
            self.future.set_exception(ActionFailure('ai_declined' if self.state == 'pending' else 'ai_failed'))
            return {'ok': True}
        if packet.operation == 'begin' and self.state == 'pending':
            self.state = 'running'
            value['expires'] = time.time() + 125
            self.lease = uuid4().hex
            return {'lease': self.lease}
        if packet.operation not in {'check', 'deliver', 'fail'} or self.state != 'running' or not self.lease or packet.lease != self.lease:
            raise HTTPException(409, 'AI approval unavailable')
        if packet.operation == 'check':
            return {'ok': True}
        if packet.operation == 'fail':
            self.future.set_exception(ActionFailure('ai_failed'))
        else:
            self.future.set_result(packet.text)
        return {'ok': True}
