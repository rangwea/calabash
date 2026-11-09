"""Execute actions through the existing ToolJobs queue and result store only."""
import asyncio
import time
from dataclasses import dataclass
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from service.actions import registry
from service.actions.models import ActionResult, ActionRun, ActionSubmission
from service.actions.office import ActionFailure


@dataclass
class Invocation:
    id: str
    action: registry.Action
    parameters: object
    result: dict | None = None
    error: dict | None = None


class ToolActions:
    def __init__(self, sdk):
        self.sdk = sdk

    def start(self, action_id, parameters, *, action_version=1, protocol_version=1):
        return self.start_batch(action_id, [parameters], action_version=action_version, protocol_version=protocol_version)

    def start_batch(self, action_id, parameters, *, action_version=1, protocol_version=1):
        if type(action_version) is not int or type(protocol_version) is not int or action_version != 1 or protocol_version != 1:
            raise ActionFailure('unsupported_action_version')
        action = registry.get(action_id)
        if not isinstance(parameters, list) or not 1 <= len(parameters) <= 20:
            raise ActionFailure('invalid_parameters')
        invocations = []
        for value in parameters:
            try:
                parsed = action.parameters.model_validate(value)
            except ValidationError:
                # ValidationError strings can include values; never carry them into ToolJobs logs.
                raise ActionFailure('invalid_parameters') from None
            self._inputs(action, parsed)
            invocations.append(Invocation(uuid4().hex, action, parsed))
        status = self.sdk.start_batch(invocations, self._execute)
        return ActionSubmission(**status, action_id=action.id, invocation_ids=[item.id for item in invocations]).model_dump()

    def _inputs(self, action, parameters):
        ids = getattr(parameters, action.input_field)
        ids = ids if isinstance(ids, list) else [ids]
        try:
            paths = [self.sdk.input_path(identity) for identity in ids]
        except (KeyError, OSError, ValueError):
            raise ActionFailure('input_unavailable') from None
        if any(path.suffix.lower() != action.extension for path in paths):
            raise ActionFailure('unsupported_format')
        return paths

    async def _execute(self, invocation):
        from core.logger import get_logger
        log = get_logger(__name__)
        started = time.monotonic()
        action = invocation.action
        destination = None
        try:
            paths = self._inputs(action, invocation.parameters)
            destination = self.sdk.output_path(invocation.parameters.output_name)
            loop = asyncio.get_running_loop()
            jobs = self.sdk.jobs
            def progress(value):
                loop.call_soon_threadsafe(jobs.report_progress, min(1.0, max(0.0, value)))
            counts = await self.sdk.io(action.handler, paths, invocation.parameters, destination, progress)
            self._inputs(action, invocation.parameters)
            output = self.sdk.add_result(destination)
            invocation.result = ActionResult(invocation_id=invocation.id, action_id=action.id, outputs=[output], counts=counts).model_dump()
            log.info('Office action id={} invocation={} version=1 status=succeeded duration_ms={}', action.id, invocation.id, round((time.monotonic() - started) * 1000))  # noqa: PLE1205 - Loguru brace formatting.
            return invocation.result
        except Exception as error:  # noqa: BLE001 - return only trusted error categories, never parser values.
            code = error.code if isinstance(error, ActionFailure) else 'processing_failed'
            invocation.error = {'code': code, 'message': str(ActionFailure(code))}
            log.error('Office action id={} invocation={} version=1 status=failed code={} exception={} duration_ms={}',  # noqa: PLE1205 - Loguru brace formatting.
                         action.id, invocation.id, code, type(error).__name__, round((time.monotonic() - started) * 1000))
            raise ActionFailure(code) from None
        finally:
            if destination is not None:
                try:
                    destination.unlink(missing_ok=True)
                    destination.parent.rmdir()
                except OSError:
                    pass

    def runs(self):
        # Same live batch as /status: no second scheduler, history database or silent replay.
        jobs = self.sdk.jobs
        if not jobs:
            return []
        return [ActionRun(invocation_id=job.value.id, action_id=job.value.action.id,
                          status=job.status, result=job.value.result, error=job.value.error).model_dump()
                for job in jobs.jobs if isinstance(job.value, Invocation)]

    async def submit(self, action_id: str, request):
        # Called by the typed SDK HTTP route, not by the authoring Agent.
        try:
            return self.start(action_id, request.parameters, action_version=request.action_version, protocol_version=request.protocol_version)
        except ActionFailure as error:
            raise HTTPException(422, str(error)) from None
