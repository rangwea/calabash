"""Host-only schedules for explicitly registered, version-pinned saved-tool tasks."""
import asyncio
import sqlite3
import time
from contextlib import closing
from uuid import uuid4

from core.local_paths import app_dir
from service.tools import tool_bundles as bundles
from service.tools.tool_workers import workers


class ToolSchedules:
    def __init__(self, workers, clock=time.time):
        self.workers = workers
        self.clock = clock
        self.active = {}
        self.closing = False
        self.lease = None
        self.lock = asyncio.Lock()
        self.wakeup = asyncio.Event()

    def database(self):
        root = app_dir()
        root.mkdir(parents=True, exist_ok=True)
        path = root / 'tool-schedules.sqlite'
        if root.is_symlink() or path.is_symlink() or path.exists() and path.stat().st_nlink != 1:
            raise ValueError('Linked schedule storage is forbidden')
        db = sqlite3.connect(path, timeout=.1)
        path.chmod(0o600)
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE IF NOT EXISTS schedules (id TEXT PRIMARY KEY, project TEXT NOT NULL, name TEXT NOT NULL, task TEXT NOT NULL, title TEXT NOT NULL, revision TEXT NOT NULL, interval INTEGER NOT NULL, next_run REAL NOT NULL, enabled INTEGER NOT NULL, status TEXT NOT NULL)')
        return db

    def rows(self):
        with closing(self.database()) as db:
            return [dict(row) for row in db.execute('SELECT * FROM schedules ORDER BY title,id')]

    async def dispatch(self, operation, arguments):
        if self.closing:
            raise ValueError('Schedules are stopping')
        async with self.lock:
            if operation == 'list' and not arguments:
                return self.rows()
            if operation == 'tasks' and set(arguments) == {'project', 'name'}:
                worker = await self.workers.open(bundles.identity(arguments['project']), bundles.identity(arguments['name']))
                return [{'name': name, 'title': value[0]} for name, value in worker.sdk.scheduled_tasks.items()]
            if operation == 'create' and set(arguments) == {'project', 'name', 'task', 'minutes', 'confirmed'}:
                if arguments['confirmed'] is not True or type(arguments['minutes']) is not int or not 1 <= arguments['minutes'] <= 10080:
                    raise ValueError('Confirm a bounded schedule')
                project, name, task = (bundles.identity(arguments[key]) for key in ('project', 'name', 'task'))
                worker = await self.workers.open(project, name)
                if task not in worker.sdk.scheduled_tasks or worker.revision != bundles.read(project, name)['revision']:
                    raise ValueError('Refresh the saved tool before scheduling')
                if len(self.rows()) >= 128:
                    raise ValueError('Schedule limit reached')
                title = worker.sdk.scheduled_tasks[task][0]
                with closing(self.database()) as db, db:
                    db.execute('INSERT INTO schedules VALUES (?,?,?,?,?,?,?,?,?,?)',
                               (uuid4().hex, project, name, task, title, worker.revision, arguments['minutes'] * 60, self.clock() + arguments['minutes'] * 60, 1, 'ready'))
                return self.rows()
            if operation in {'pause', 'resume', 'remove', 'run'} and set(arguments) == {'id', 'confirmed'}:
                if arguments['confirmed'] is not True or not isinstance(arguments['id'], str) or len(arguments['id']) != 32:
                    raise ValueError('Schedule confirmation required')
                row = next((row for row in self.rows() if row['id'] == arguments['id']), None)
                if row is None:
                    raise ValueError('Schedule unavailable')
                if operation in {'resume', 'run'} and bundles.read(row['project'], row['name'])['revision'] != row['revision']:
                    raise ValueError('The tool changed; review and create a new schedule')
                if operation == 'run':
                    if row['id'] in self.active or not await self._submit(row):
                        raise ValueError('Schedule is already running')
                    return self.rows()
                with closing(self.database()) as db, db:
                    if operation == 'remove':
                        db.execute('DELETE FROM schedules WHERE id=?', (row['id'],))
                    else:
                        db.execute('UPDATE schedules SET enabled=?,next_run=? WHERE id=?', (int(operation == 'resume'), self.clock() + row['interval'], row['id']))
                return self.rows()
            raise ValueError('Invalid schedule operation')

    async def tick(self):
        if self.closing:
            return
        async with self.lock:
            for row in self.rows():
                if not row['enabled'] or row['next_run'] > self.clock() or row['id'] in self.active:
                    continue
                try:
                    source = bundles.read(row['project'], row['name'])
                    if source['revision'] != row['revision']:
                        with closing(self.database()) as db, db:
                            db.execute("UPDATE schedules SET enabled=0,status='changed' WHERE id=?", (row['id'],))
                        continue
                    await self._submit(row)
                except Exception:  # noqa: BLE001 - arbitrary tool startup must not stop the shared scheduler.
                    from core.logger import get_logger
                    get_logger(__name__).warning('Scheduled task unavailable id={}', row['id'])
                    with closing(self.database()) as db, db:
                        db.execute("UPDATE schedules SET enabled=0,status='failed' WHERE id=?", (row['id'],))

    async def _submit(self, row):
        worker = await self.workers.open(row['project'], row['name'])
        if worker.revision != row['revision'] or row['task'] not in worker.sdk.scheduled_tasks:
            raise ValueError('Saved task unavailable')
        if row['status'] == 'running' or worker.sdk.status()['running']:
            return False
        key = self.workers.key(row['project'], row['name'])
        with closing(self.database()) as db, db:
            claimed = db.execute("UPDATE schedules SET next_run=?,status='running' WHERE id=? AND status != 'running'", (self.clock() + row['interval'], row['id'])).rowcount
            if not claimed:
                return False
        try:
            with worker.log_run.context():
                worker.sdk.start_registered_task(row['task'])
        except Exception:  # Admission can fail before executing the handler.
            with closing(self.database()) as db, db:
                db.execute("UPDATE schedules SET enabled=0,status='failed' WHERE id=?", (row['id'],))
            raise
        self.workers.schedule_holds[key] = self.workers.schedule_holds.get(key, 0) + 1
        self.active[row['id']] = asyncio.create_task(self._finish(row['id'], key, worker.sdk.task, worker.sdk.jobs))
        return True

    async def _finish(self, identity, key, task, jobs):
        try:
            await asyncio.shield(task)
        finally:
            try:
                with closing(self.database()) as db, db:
                    db.execute('UPDATE schedules SET status=?,enabled=CASE WHEN ? THEN enabled ELSE 0 END WHERE id=?', (jobs.status, int(jobs.status == 'succeeded'), identity))
            finally:
                self.active.pop(identity, None)
                remaining = self.workers.schedule_holds.get(key, 1) - 1
                if remaining:
                    self.workers.schedule_holds[key] = remaining
                else:
                    self.workers.schedule_holds.pop(key, None)

    async def run(self):
        from service.tools.work_drafts import _os_lock
        path = app_dir() / 'agent/tool-schedules.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink() or path.is_symlink():
            raise ValueError('Linked scheduler lease is forbidden')
        try:
            self.lease = _os_lock(path)
            self.lease.__enter__()
        except ValueError:
            self.lease = None
            return  # A second desktop instance must not duplicate scheduled work.
        try:
            with closing(self.database()) as db, db:
                db.execute("UPDATE schedules SET enabled=0,status='interrupted' WHERE status='running'")
                db.execute("UPDATE schedules SET next_run=?+interval WHERE enabled=1 AND next_run<=?", (self.clock(), self.clock()))
            while not self.closing:
                try:
                    await self.tick()
                except (sqlite3.Error, OSError, ValueError):
                    from core.logger import get_logger
                    get_logger(__name__).warning('Tool schedule storage temporarily unavailable')
                try:
                    await asyncio.wait_for(self.wakeup.wait(), 1)
                except TimeoutError:
                    pass
        finally:
            self.closing = True
            await asyncio.gather(*self.active.values(), return_exceptions=True)
            self.lease.__exit__(None, None, None)
            self.lease = None

    def start(self):
        self.closing = False
        self.wakeup = asyncio.Event()

    def stop(self):
        self.closing = True
        self.wakeup.set()


schedules = ToolSchedules(workers)
