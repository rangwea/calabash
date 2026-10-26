"""Serial batch state with cooperative cancellation and failed-only retry."""

import asyncio
from dataclasses import dataclass

from service.tools import tool_activity


@dataclass
class Job:
    value: object
    status: str = "queued"
    result: object = None


class ToolJobs:
    def __init__(self, values, *, owner=None):
        self.jobs = [Job(value) for value in values]
        self.running = False
        self.cancelling = False
        self.owner = owner
        self.status = "queued"
        self.item_progress = 0.0
        self._changed = None

    @property
    def counts(self):
        return {state: sum(job.status == state for job in self.jobs) for state in ("queued", "running", "succeeded", "failed", "cancelled")}

    @property
    def progress(self):
        counts = self.counts
        return min(1.0, (counts["succeeded"] + counts["failed"] + self.item_progress) / max(1, len(self.jobs)))

    def _notify(self):
        if self._changed:
            try:
                self._changed()
            except Exception:  # noqa: BLE001 - detached UI must not abandon an active writer.
                from core.logger import get_logger
                get_logger(__name__).warning("Task observer unavailable; processing continues")

    def report_progress(self, value):
        """Call on the event loop, not from blocking worker code."""
        if not 0 <= value <= 1:
            raise ValueError("Progress must be between zero and one")
        if self.running:
            self.item_progress = max(self.item_progress, float(value))
            self._notify()

    def cancel(self):
        if self.running and not self.cancelling:
            self.cancelling = True
            self.status = "cancelling"
            self._notify()

    async def run(self, handler, *, retry_failed=False, changed=None):
        """handler is async; offload blocking work using run.io_bound inside it.

        Cancellation stops scheduling after the current item really completes.
        Never cancel the task to simulate interruption of a blocking writer.
        """
        if self.running:
            raise RuntimeError("Batch is already running")
        candidates = [job for job in self.jobs if job.status == ("failed" if retry_failed else "queued")]
        if not candidates:
            return
        tool_activity.acquire(self)
        self.running = True
        self.cancelling = False
        self.status = "running"
        self._changed = changed
        interrupted = False

        try:
            self._notify()
            for job in candidates:
                tool_activity.check_stop_request()
                if self.cancelling:
                    job.status = "cancelled"
                    self._notify()
                    continue
                job.status = "running"
                self.item_progress = 0.0
                self._notify()
                # A UI disconnect/cancel must not abandon a still-running writer.
                try:
                    current = asyncio.create_task(handler(job.value))
                    while True:
                        try:
                            job.result = await asyncio.shield(current)
                            break
                        except asyncio.CancelledError:
                            if current.cancelled():
                                raise
                            interrupted = True
                            self.cancel()
                    job.status = "succeeded"
                except asyncio.CancelledError:
                    job.status = "cancelled"
                    interrupted = True
                    self.cancel()
                except Exception:  # noqa: BLE001 - isolate arbitrary user tool handlers per item.
                    from core.logger import get_logger
                    get_logger(__name__).exception("Tool item execution failed")
                    job.status = "failed"
                self.item_progress = 0.0
                self._notify()
        finally:
            self.running = False
            self.status = "cancelled" if self.cancelling else "failed" if any(job.status == "failed" for job in self.jobs) else "succeeded"
            self.cancelling = False
            try:
                self._notify()
            finally:
                self._changed = None
                tool_activity.release(self)
        if interrupted:
            raise asyncio.CancelledError


class ToolTask(ToolJobs):
    """One-shot operations use the same safe cancellation and progress contract."""

    def __init__(self, *, owner=None):
        super().__init__([None], owner=owner)

    @property
    def result(self):
        return self.jobs[0].result

    def reset(self):
        if self.running:
            return False
        self.jobs = [Job(None)]
        self.status = "queued"
        self.item_progress = 0.0
        return True

    async def run(self, handler, *, retry_failed=False, changed=None):
        if self.running:
            raise RuntimeError("Task is already running")
        if not retry_failed:
            self.jobs = [Job(None)]

        async def single(_):
            return await handler()

        await super().run(single, retry_failed=retry_failed, changed=changed)
