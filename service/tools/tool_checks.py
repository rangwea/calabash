"""Revision-bound compiler results shared by preview, Agent and publication."""
import asyncio
import shutil
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from core.local_paths import app_dir
from service.tools import tool_bundles as bundles
from service.tools.tool_workers import ROOT, build_bundle, frontend_runtime


@dataclass
class Check:
    revision: str
    state: str = 'checking'
    diagnostics: list = field(default_factory=list)
    root: Path | None = None
    task: asyncio.Task | None = None
    users: int = 0
    owner: tuple | None = None
    touched: float = field(default_factory=time.monotonic)

    def public(self):
        return {'revision': self.revision, 'state': self.state, 'diagnostics': self.diagnostics}


def compiler_version():
    node, script = frontend_runtime()
    paths = [Path(node), script, script.parent / 'tool_runtime_ui.tsx', script.parent / 'tool_api_client.ts',
             Path(__file__).with_name('api_contracts.py'),
             script.parent.parent / 'component/frontend_probe.js', ROOT / 'package-lock.json']
    return tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths if p.exists())


class ToolChecks:
    def __init__(self):
        self.entries = {}
        self.limit = asyncio.Semaphore(2)

    def prune(self):
        idle = sorted(((key, value) for key, value in self.entries.items()
                       if value.task.done() and not value.users), key=lambda item: item[1].touched)
        for key, value in idle:
            if len(self.entries) <= 16 and time.monotonic() - value.touched < 1800:
                continue
            self.entries.pop(key)
            if value.root and value.root.parent == app_dir() / 'builds' and not value.root.is_symlink():
                shutil.rmtree(value.root, ignore_errors=True)

    def ensure(self, project, name, chat_id, source, retry=False):
        if bundles.revision(source['files']) != source['revision']:
            raise ValueError('Source revision does not match compiler input')
        self.prune()
        key = (str(app_dir()), project, name, chat_id, source['revision'], compiler_version())
        entry = self.entries.get(key)
        if entry and retry and entry.state == 'failed':
            self.entries.pop(key)
            if entry.root and entry.root.parent == app_dir() / 'builds' and not entry.root.is_symlink():
                shutil.rmtree(entry.root, ignore_errors=True)
            entry = None
        if entry and entry.state == 'passed' and not (entry.root / 'dist/index.html').is_file():
            self.entries.pop(key)
            entry = None
        if entry is None:
            if len(self.entries) >= 32:
                raise ValueError('Too many pending tool checks; retry shortly')
            entry = Check(source['revision'], owner=(project, name, chat_id))
            self.entries[key] = entry
            entry.task = asyncio.create_task(self.run(entry, dict(source['files'])))
        entry.touched = time.monotonic()
        return entry

    async def run(self, entry, files):
        from core.logger import get_logger
        from service.tools.tool_workers import FrontendBuildError
        try:
            async with self.limit:
                entry.root = await build_bundle(files)
            entry.state = 'passed'
        except FrontendBuildError as error:
            entry.root = error.root
            entry.diagnostics = error.diagnostics
            entry.state = 'failed'
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - background failures must leave checking state
            get_logger(__name__).exception('Tool frontend check failed')
            entry.diagnostics = [{'message': '检查未完成，请重试；详细错误保留在本机日志'}]
            entry.state = 'failed'
        if entry.owner:
            from service.tools.check_records import record
            try:
                record(*entry.owner, entry.public(), entry.root)
            except (OSError, ValueError):
                get_logger(__name__).exception('Unable to preserve local build diagnostics')

    @asynccontextmanager
    async def verified(self, project, name, chat_id, source):
        from core.i18n import t
        entry = self.ensure(project, name, chat_id, source)
        entry.users += 1
        try:
            await asyncio.shield(entry.task)
            if entry.state != 'passed':
                raise ValueError(t('当前版本检查失败，请先修复预览中的错误'))
            yield entry.root
        finally:
            entry.users -= 1
            self.prune()

    async def close(self):
        for entry in self.entries.values():
            if not entry.task.done():
                entry.task.cancel()
        await asyncio.gather(*(e.task for e in self.entries.values() if not e.task.done()), return_exceptions=True)
        for entry in self.entries.values():
            if entry.root and entry.root.parent == app_dir() / 'builds' and not entry.root.is_symlink():
                shutil.rmtree(entry.root, ignore_errors=True)
        self.entries.clear()


checks = ToolChecks()
