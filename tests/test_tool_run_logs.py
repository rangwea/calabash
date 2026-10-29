import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from core import tool_run_logs as logs
from core.logger import get_logger


class RunLogsFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        for name, value in [('logs_dir', self.home / 'logs'), ('app_dir', self.home)]:
            patcher = patch.object(logs, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.runs = []
        self.addCleanup(self.close_runs)

    def close_runs(self):
        for run in self.runs:
            while run.references:
                run.close()

    def start(self, **options):
        run = logs.start('demo', 'example', **options)
        self.runs.append(run)
        return run

    def age(self, run, seconds):
        path = run.path.parent / 'run.json'
        metadata = json.loads(path.read_text())
        metadata['created'] = time.time() - seconds
        path.write_text(json.dumps(metadata))


class RunLogTests(RunLogsFixture, unittest.TestCase):
    def test_same_tool_and_preview_runs_have_independent_callback_logs(self):
        one = self.start(preview_key='same-preview')
        two = self.start(preview_key='same-preview')
        one.attach_module('synthetic_run_' + one.id)
        two.attach_module('synthetic_run_' + two.id)
        logging.getLogger('synthetic_run_' + one.id).warning('one callback')
        logging.getLogger('synthetic_run_' + two.id).warning('two callback')
        with one.context():
            get_logger('synthetic').info('one worker')
        self.assertIn('one callback', one.path.read_text())
        self.assertIn('one worker', one.path.read_text())
        self.assertNotIn('two callback', one.path.read_text())
        self.assertNotIn('one callback', two.path.read_text())
        self.assertEqual(two.path, logs.latest_preview('same-preview'))
        one.close()
        self.assertFalse(logging.getLogger('synthetic_run_' + one.id).handlers)

    def test_retains_last_five_and_protects_open_run(self):
        protected = self.start()
        for _ in range(8):
            self.start().close()
        folders = list(protected.path.parent.parent.iterdir())
        self.assertTrue(protected.path.exists())
        self.assertLessEqual(len(folders), logs.KEEP_RUNS + 1)
        protected.close()
        self.assertFalse(protected.path.exists())
        self.assertEqual(5, len(list(protected.path.parent.parent.iterdir())))

    def test_old_runs_removed_only_after_ownership_ends(self):
        run = self.start()
        self.age(run, logs.MAX_AGE + 60)
        logs.cleanup()
        self.assertTrue(run.path.exists())
        run.close()
        self.assertFalse(run.path.parent.exists())

    def test_pending_active_repair_is_pinned_until_completion(self):
        run = self.start()
        with closing(sqlite3.connect(self.home / 'conversations.db')) as db, db:
            db.execute('CREATE TABLE tool_repairs(data TEXT, state TEXT, started TEXT)')
            db.execute("INSERT INTO tool_repairs VALUES (?, 'queued', NULL)", (json.dumps({'log_run_id': run.id}),))
        self.age(run, logs.MAX_AGE + 60)
        run.close()
        logs.cleanup()
        self.assertTrue(run.path.exists())
        with closing(sqlite3.connect(self.home / 'conversations.db')) as db, db:
            db.execute("UPDATE tool_repairs SET state='completed'")
        logs.cleanup()
        self.assertFalse(run.path.parent.exists())

    def test_rotation_limits_total_size_even_for_one_huge_entry(self):
        with patch.object(logs, 'MAX_RUN_BYTES', 2048):
            run = self.start()
            for _ in range(12):
                run.writer.write('a' * 800)
            run.writer.write('b' * 10000)
            files = list(run.path.parent.glob('*.log'))
            self.assertLessEqual(sum(path.stat().st_size for path in files), 2048)
            self.assertLessEqual(len(files), 2)
            self.assertIn('truncated', run.path.read_text())

    def test_global_capacity_cleans_old_inactive_runs_but_not_active(self):
        old = self.start()
        old.writer.write('old' * 100)
        old.close()
        active = self.start()
        active.writer.write('active' * 100)
        with patch.object(logs, 'MAX_TOTAL_BYTES', 1):
            logs.cleanup()
        self.assertFalse(old.path.exists())
        self.assertTrue(active.path.exists())

    def test_symlink_and_unknown_directories_are_not_followed_or_deleted(self):
        run = self.start()
        external = self.home / 'external'
        external.mkdir()
        (external / 'business.txt').write_text('untouched')
        link = run.path.parent.parent / ('b' * 32)
        link.symlink_to(external, target_is_directory=True)
        unknown = run.path.parent.parent / ('c' * 32)
        unknown.mkdir()
        (unknown / 'unknown.txt').write_text('untouched')
        logs.cleanup(now=time.time() + logs.MAX_AGE + 10)
        self.assertTrue(link.is_symlink())
        self.assertTrue((external / 'business.txt').exists())
        self.assertTrue((unknown / 'unknown.txt').exists())
        with self.assertRaises(ValueError):
            logs.directory('demo', 'example', 'b' * 32)
    def test_cli_defaults_to_latest_published_run_and_accepts_exact_run(self):
        first = self.start()
        first.writer.write('first-only\n')
        second = self.start()
        second.writer.write('second-only\n')
        preview = self.start(preview_key='preview-only')
        preview.writer.write('preview-hidden\n')
        script = Path(__file__).resolve().parents[1] / 'agent/skills/calabash/scripts/tool-cli.py'
        def invoke(*options):
            process = subprocess.run([sys.executable, str(script), 'toollog', 'demo', 'example', *options],
                                     env={**os.environ, 'CALABASH_HOME': str(self.home)}, capture_output=True, text=True, check=False)
            self.assertEqual(0, process.returncode, process.stderr)
            return process.stdout
        output = invoke()
        self.assertIn('second-only', output)
        self.assertNotIn('first-only', output)
        self.assertNotIn('preview-hidden', output)
        self.assertIn('first-only', invoke('--run', first.id))


class RunJobLogsTests(RunLogsFixture, unittest.IsolatedAsyncioTestCase):
    async def test_closing_page_does_not_delete_or_unbind_running_job_logs(self):
        from service.tools.tool_jobs import ToolJobs
        run = self.start()
        started, finish = asyncio.Event(), asyncio.Event()
        with run.context():
            jobs = ToolJobs([1], owner='synthetic-log-test')
        async def handle(_):
            started.set()
            await finish.wait()
            get_logger('synthetic').info('job finished after page close')
        task = asyncio.create_task(jobs.run(handle))
        await started.wait()
        run.close()
        self.assertIn(run.id, logs._active)
        self.age(run, logs.MAX_AGE + 60)
        logs.cleanup()
        self.assertTrue(run.path.exists())
        finish.set()
        await task
        self.assertNotIn(run.id, logs._active)
        self.assertFalse(run.path.parent.exists())
