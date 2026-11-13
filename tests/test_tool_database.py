"""Tool data survives runtimes, with isolated databases and real transactions."""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from service.tools.tool_sdk import ToolSDK


class ToolDatabaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {'HOME': temporary.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.sdk = ToolSDK('demo', 'customers')
        with self.sdk.database(write=True) as db:
            db.execute('CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)')
            db.execute('CREATE TABLE notes (customer_id INTEGER REFERENCES customers(id), text TEXT)')

    def test_business_tables_settings_and_tool_isolation_survive_reopening(self):
        legacy = self.sdk.data_dir / 'settings.json'
        legacy.write_text('{"old":true}')
        with self.sdk.database(write=True) as db:
            db.execute('INSERT INTO customers(name) VALUES (?)', ('Synthetic',))
        self.sdk.set_setting('layout', {'columns': ['name'], 'dense': True})
        reopened = ToolSDK('demo', 'customers')
        with reopened.database() as db:
            self.assertEqual('Synthetic', db.execute('SELECT name FROM customers').fetchone()['name'])
        self.assertTrue(reopened.get_setting('layout')['dense'])
        other = ToolSDK('demo', 'other')
        self.assertIsNone(other.get_setting('layout'))
        with other.database() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name = 'customers'").fetchone())
        self.assertEqual('{"old":true}', legacy.read_text())
        self.assertEqual([legacy], list(self.sdk.data_dir.glob('*.json')))

    def test_rollback_foreign_keys_read_only_and_connection_closure(self):
        with self.assertRaises(sqlite3.IntegrityError), self.sdk.database(write=True) as db:
            db.execute('INSERT INTO customers(id, name) VALUES (1, ?)', ('Not committed',))
            db.execute('INSERT INTO notes(customer_id, text) VALUES (2, ?)', ('Invalid reference',))
        with self.sdk.database() as db:
            self.assertEqual(0, db.execute('SELECT COUNT(*) FROM customers').fetchone()[0])
            self.assertEqual(15000, db.execute('PRAGMA busy_timeout').fetchone()[0])
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')
        with self.assertRaises(sqlite3.OperationalError), self.sdk.database() as db:
            db.execute('INSERT INTO customers(name) VALUES (?)', ('Read only',))
        with self.assertRaises(KeyboardInterrupt), self.sdk.database(write=True) as db:
            db.execute('INSERT INTO customers(name) VALUES (?)', ('Cancelled',))
            raise KeyboardInterrupt
        with self.sdk.database() as db:
            self.assertEqual(0, db.execute('SELECT COUNT(*) FROM customers').fetchone()[0])

    def test_concurrent_threads_and_processes_do_not_lose_updates(self):
        with self.sdk.database(write=True) as db:
            db.execute('CREATE TABLE counter (id INTEGER PRIMARY KEY, value INTEGER NOT NULL)')
            db.execute('INSERT INTO counter VALUES (1, 0)')
        def increment(_):
            runtime = ToolSDK('demo', 'customers')
            for _ in range(20):
                with runtime.database(write=True) as db:
                    value = db.execute('SELECT value FROM counter WHERE id = 1').fetchone()[0]
                    db.execute('UPDATE counter SET value = ? WHERE id = 1', (value + 1,))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(increment, range(4)))
        source = '''from service.tools.tool_sdk import ToolSDK
sdk = ToolSDK('demo', 'customers')
for _ in range(20):
    with sdk.database(write=True) as db:
        value = db.execute('SELECT value FROM counter WHERE id=1').fetchone()[0]
        db.execute('UPDATE counter SET value=? WHERE id=1', (value+1,))
'''
        children = [subprocess.Popen([sys.executable, '-c', source], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
        for child in children:
            _, errors = child.communicate(timeout=30)
            self.assertEqual(0, child.returncode, errors.decode())
        with self.sdk.database() as db:
            self.assertEqual(140, db.execute('SELECT value FROM counter').fetchone()[0])

    def test_linked_database_directory_and_sidecar_are_rejected(self):
        external = self.sdk.data_dir.parent / 'external.txt'
        external.write_text('unchanged')
        for index, suffix in enumerate(('', '-journal', '-wal', '-shm')):
            runtime = ToolSDK('demo', 'linked' + str(index))
            linked = runtime.data_dir / ('data.sqlite' + suffix)
            linked.symlink_to(external)
            with self.assertRaises(ValueError), runtime.database():
                pass
        root = self.sdk.data_dir.parent / 'linked_directory'
        root.symlink_to(self.sdk.data_dir, target_is_directory=True)
        with self.assertRaises(ValueError):
            ToolSDK('demo', 'linked_directory')
        self.assertEqual('unchanged', external.read_text())

