"""Synthetic, explicitly authorized scheduled work; never call a model."""
import asyncio
from contextlib import closing

from service.tools.tool_schedules import ToolSchedules
from tests.test_shared_runtime import RuntimeFixture


class ScheduleTests(RuntimeFixture):
    async def test_authorized_plan_runs_once_per_deadline_and_pauses_on_source_change(self):
        first = self.publish('one', 'first')
        now = [1000.0]
        schedules = ToolSchedules(self.manager, lambda: now[0])
        parameters = {'project': 'demo', 'name': 'one', 'task': 'refresh', 'minutes': 1, 'confirmed': False}
        with self.assertRaises(ValueError):
            await schedules.dispatch('create', parameters)
        self.assertEqual([], schedules.rows())
        self.assertEqual('refresh', (await schedules.dispatch('tasks', {'project': 'demo', 'name': 'one'}))[0]['name'])
        rows = await schedules.dispatch('create', {**parameters, 'confirmed': True})
        await schedules.tick()
        worker = await self.manager.open('demo', 'one')
        self.assertEqual(0, worker.sdk.get_setting('runs', 0))
        now[0] = 1060
        await schedules.tick()
        await schedules.tick()
        await asyncio.gather(*schedules.active.values())
        self.assertEqual(1, worker.sdk.get_setting('runs'))
        self.assertEqual('succeeded', schedules.rows()[0]['status'])
        # Reopening the manager reads metadata only; no task is replayed.
        restored = ToolSchedules(self.manager, lambda: now[0])
        self.assertEqual(rows[0]['id'], restored.rows()[0]['id'])
        self.publish('one', 'new version', first['revision'])
        now[0] = 1120
        await schedules.tick()
        self.assertFalse(schedules.rows()[0]['enabled'])
        self.assertEqual('changed', schedules.rows()[0]['status'])
        self.assertEqual(1, worker.sdk.get_setting('runs'))
        with self.assertRaises(ValueError):
            await schedules.dispatch('resume', {'id': rows[0]['id'], 'confirmed': True})

    async def test_pause_remove_and_interrupted_work_are_not_replayed(self):
        self.publish('one', 'first')
        schedules = ToolSchedules(self.manager, lambda: 1000)
        rows = await schedules.dispatch('create', {'project': 'demo', 'name': 'one', 'task': 'refresh', 'minutes': 1, 'confirmed': True})
        identity = rows[0]['id']
        await schedules.dispatch('pause', {'id': identity, 'confirmed': True})
        self.assertFalse(schedules.rows()[0]['enabled'])
        with closing(schedules.database()) as db, db:
            db.execute("UPDATE schedules SET status='running',enabled=1,next_run=0")
        schedules.start()
        runner = asyncio.create_task(schedules.run())
        await asyncio.sleep(.02)
        schedules.stop()
        await runner
        self.assertEqual('interrupted', schedules.rows()[0]['status'])
        self.assertFalse(schedules.rows()[0]['enabled'])
        schedules.start()
        await schedules.dispatch('remove', {'id': identity, 'confirmed': True})
        self.assertEqual([], schedules.rows())

    async def test_closing_a_tool_view_does_not_cancel_accepted_scheduled_work(self):
        self.publish('one', 'first')
        schedules = ToolSchedules(self.manager, lambda: 1000)
        rows = await schedules.dispatch('create', {'project': 'demo', 'name': 'one', 'task': 'refresh', 'minutes': 1, 'confirmed': True})
        worker = await self.manager.open('demo', 'one')
        entered, finish = asyncio.Event(), asyncio.Event()
        async def handler():
            entered.set()
            await finish.wait()
            worker.sdk.set_setting('completed', True)
        worker.sdk.scheduled_tasks['refresh'] = ('Synthetic refresh', handler)
        await schedules.dispatch('pause', {'id': rows[0]['id'], 'confirmed': True})
        await schedules.dispatch('run', {'id': rows[0]['id'], 'confirmed': True})
        await entered.wait()
        try:
            await self.manager.close('demo', 'one')
            self.assertTrue(worker.alive)
            self.assertFalse(worker.sdk._cancel_pending)
        finally:
            finish.set()
            await asyncio.gather(*schedules.active.values())
        self.assertTrue(worker.sdk.get_setting('completed'))
        self.assertFalse(schedules.rows()[0]['enabled'], 'Run now must not resume a paused plan')
        await self.manager.close('demo', 'one')

    async def test_missed_deadlines_are_not_replayed_and_failed_tasks_pause(self):
        self.publish('one', 'first')
        now = [1000.0]
        schedules = ToolSchedules(self.manager, lambda: now[0])
        rows = await schedules.dispatch('create', {'project': 'demo', 'name': 'one', 'task': 'refresh', 'minutes': 1, 'confirmed': True})
        worker = await self.manager.open('demo', 'one')
        now[0] = 2000
        schedules.start()
        runner = asyncio.create_task(schedules.run())
        await asyncio.sleep(.03)
        schedules.stop()
        await runner
        self.assertEqual(0, worker.sdk.get_setting('runs', 0))
        self.assertEqual(2060, schedules.rows()[0]['next_run'])
        schedules.start()
        async def fail():
            raise ValueError('synthetic failure')
        worker.sdk.scheduled_tasks['refresh'] = ('Synthetic failure', fail)
        await schedules.dispatch('run', {'id': rows[0]['id'], 'confirmed': True})
        await asyncio.gather(*schedules.active.values())
        self.assertEqual('failed', schedules.rows()[0]['status'])
        self.assertFalse(schedules.rows()[0]['enabled'])
