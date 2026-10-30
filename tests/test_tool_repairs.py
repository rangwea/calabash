import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from service.chat import ai_chat, agent_model
from service.chat import model_providers
from service.tools import tool_repairs


class RepairFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "tools/demo/example.py"
        self.path.parent.mkdir(parents=True)
        self.path.write_text('api_key = "private-tool-key"\ndef main():\n    pass\n')
        from service.tools import preview_service
        from core import tool_run_logs
        for target, value in [('logs_dir', self.root / 'logs'), ('app_dir', self.root)]:
            patcher = patch.object(tool_run_logs, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, value in (("_TMP_DIR", self.root / "previews"), ("_PREVIEW_META_DIR", self.root / "previews/_meta")):
            patcher = patch.object(preview_service, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, value in (("app_dir", self.root), ("tools_dir", self.root / "tools")):
            patcher = patch.object(ai_chat, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(model_providers, "active", return_value=("deepseek", "test", {"key": "provider-key", "base_url": "https://example.test"}))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(model_providers, "load", return_value={"connections": {}})
        patcher.start()
        self.addCleanup(patcher.stop)

    def report(self):
        return tool_repairs.capture(ValueError("secret business body"), "demo", "example")


class RepairTests(RepairFixture, unittest.TestCase):
    def test_actual_nested_drawer_failure_has_safe_host_contract_diagnosis(self):
        from nicegui import ui
        self.path.write_text('from nicegui import ui\ndef main():\n    ui.left_drawer(fixed=False)\n')
        namespace = {}
        exec(compile(self.path.read_text(), str(self.path), 'exec'), namespace)
        with ui.column() as container:
            try:
                namespace['main']()
            except RuntimeError as error:
                report = tool_repairs.get(tool_repairs.capture(error, 'demo', 'example'))
        container.delete()
        self.assertEqual('RuntimeError', report['exception'])
        self.assertEqual([3], report['lines'])
        self.assertNotIn('diagnosis', report)

    def test_syntax_preflight_line_is_recovered_without_source_or_error_text(self):
        self.path.write_text('def main():\n    private_value =\n')
        try:
            compile(self.path.read_text(), str(self.path), 'exec')
        except SyntaxError as error:
            report = tool_repairs.get(tool_repairs.capture(error, 'demo', 'example'))
        self.assertEqual('SyntaxError', report['exception'])
        self.assertEqual([2], report['lines'])
        self.assertNotIn('private_value', tool_repairs.summary(report))

    def test_suppressed_stop_iteration_cannot_hide_missing_audio_argument(self):
        self.path.write_text('def main():\n    from nicegui import ui\n    ui.audio()\n')
        namespace = {}
        exec(compile(self.path.read_text(), str(self.path), 'exec'), namespace)
        try:
            namespace['main']()
        except TypeError as error:
            self.assertTrue(error.__suppress_context__)
            self.assertIsInstance(error.__context__, StopIteration)
            report = tool_repairs.get(tool_repairs.capture(error, 'demo', 'example'))
        self.assertEqual('TypeError', report['exception'])
        self.assertEqual([3], report['lines'])
        self.assertNotIn('diagnosis', report)

    def test_explicit_cause_retains_outer_tool_frame_without_sending_messages(self):
        self.path.write_text('def main(helper):\n    try:\n        helper()\n    except ValueError as error:\n        raise RuntimeError("private wrapper") from error\n')
        namespace = {}
        exec(compile(self.path.read_text(), str(self.path), 'exec'), namespace)
        def helper():
            raise ValueError('private business value')
        try:
            namespace['main'](helper)
        except RuntimeError as error:
            report = tool_repairs.get(tool_repairs.capture(error, 'demo', 'example'))
        self.assertEqual('ValueError', report['exception'])
        self.assertIn(5, report['lines'])
        self.assertNotIn('private', tool_repairs.summary(report))

    def test_preflight_api_error_retains_safe_diagnosis(self):
        from service.tools.tool_runtime import ToolEntryPointError
        self.path.write_text('from component.tool_results import ToolResults\ndef main():\n    results = ToolResults()\n    results.mount()\n')
        report = tool_repairs.get(tool_repairs.capture(ToolEntryPointError('private'), 'demo', 'example'))
        self.assertEqual('ToolEntryPointError', report['exception'])
        self.assertNotIn('diagnosis', report)
        self.assertNotIn('private', tool_repairs.summary(report))

    def test_safe_api_diagnosis_uses_structured_attribute_metadata(self):
        from component.tool_results import ToolResults
        result = object.__new__(ToolResults)
        self.path.write_text('def fail(result):\n    result.mount()\n')
        namespace = {}
        exec(compile(self.path.read_text(), str(self.path.resolve()), 'exec'), namespace)
        try:
            namespace['fail'](result)
        except AttributeError as exc:
            error = exc
        report = tool_repairs.get(tool_repairs.capture(error, 'demo', 'example'))
        summary = tool_repairs.summary(report)
        self.assertNotIn('diagnosis', summary)
        self.assertNotIn('secret', summary)
        unknown = AttributeError('secret', name='mount', obj=object())
        report = tool_repairs.get(tool_repairs.capture(unknown, 'demo', 'example'))
        self.assertNotIn('diagnosis', report)

    def test_summary_does_not_include_raw_error_and_requires_consent(self):
        report_id = self.report()
        report = tool_repairs.get(report_id)
        self.assertNotIn("secret", tool_repairs.summary(report))
        self.assertIsNone(tool_repairs.claim("anything"))
        with self.assertRaises(ValueError):
            tool_repairs.approve(report_id, "wrong-model")
        chat_id = tool_repairs.approve(report_id, tool_repairs.model_fingerprint())
        self.assertEqual(chat_id, tool_repairs.approve(report_id, tool_repairs.model_fingerprint()))
        self.assertEqual(report_id, tool_repairs.claim(chat_id)["id"])
        self.assertIsNone(tool_repairs.claim(chat_id))
        tool_repairs.finish(report_id, False)
        self.assertEqual("failed", tool_repairs.get(report_id)["state"])

    def test_published_repair_reuses_existing_edit_conversation(self):
        chat_id = ai_chat.get_or_create_tool_chat('demo', 'example', 'Example')
        history = ai_chat.read_chat(chat_id) + [{'role': 'user', 'content': 'Keep my new blue UI'}]
        ai_chat.save_chat(chat_id, history)
        report_id = self.report()
        self.assertEqual(chat_id, tool_repairs.approve(report_id, tool_repairs.model_fingerprint()))
        self.assertEqual(history, ai_chat.read_chat(chat_id))
        report = tool_repairs.claim(chat_id)
        message = tool_repairs.request_message(report)
        self.assertIn(report['log_run_id'], message)
        self.assertNotIn('secret business body', message)
        self.assertNotIn('```', message)

    def test_repair_restricts_target_redacts_credentials_and_requires_read(self):
        session = tool_repairs.RepairSession(tool_repairs.get(self.report()))
        api = session.execute('read_component_api', {'component': 'ToolResults'})
        self.assertIn('refresh', api['methods'])
        self.assertIsNone(session.read_revision)
        args = {"project": "demo", "name": "example"}
        self.assertIn("error", session.execute("read_attachment", args))
        self.assertIn("error", session.execute("read_tool", {**args, "name": "other"}))
        self.assertIn("error", session.execute("preview_tool", {**args, "content": "def main(): pass"}))
        result = session.execute("read_tool", args)
        self.assertNotIn("private-tool-key", result["content"])
        saved = session.execute("write_tool", {**args, **result})
        self.assertEqual('static_only', saved['validation'])
        self.assertFalse(saved['executed'])
        self.assertFalse(saved['runtime_verified'])
        self.assertTrue(saved["requires_manual_run"])
        self.assertTrue(saved["preview_url"].startswith('/preview/'))
        self.assertIn('?context=', saved['preview_url'])
        from urllib.parse import urlsplit, parse_qs
        from service.files import tool_inputs
        from service.tools import preview_service
        parsed = urlsplit(saved['preview_url'])
        key = parsed.path.rsplit('/', 1)[1]
        owner, _ = tool_inputs.owner(parse_qs(parsed.query)['context'][0], key)
        self.assertEqual('tool:demo/example', owner)
        self.assertIn('private-tool-key', preview_service.get_preview_file(key).read_text())
        self.assertIn("private-tool-key", self.path.read_text())
        self.assertIn("error", session.execute("write_tool", {**args, **result}))

    def test_deleted_chat_cannot_claim_or_reapprove(self):
        report_id = self.report()
        chat_id = tool_repairs.approve(report_id, tool_repairs.model_fingerprint())
        ai_chat.delete_chat(chat_id)
        self.assertIsNone(tool_repairs.claim(chat_id))
        tool_repairs.finish(report_id, False)
        with self.assertRaises(ValueError):
            tool_repairs.approve(report_id, tool_repairs.model_fingerprint())

    def test_concurrent_file_edit_invalidates_revision(self):
        session = tool_repairs.RepairSession(tool_repairs.get(self.report()))
        args = {"project": "demo", "name": "example"}
        result = session.execute("read_tool", args)
        self.path.write_text("def main():\n    return 123\n")
        self.assertIn("error", session.execute("write_tool", {**args, **result}))
        self.assertIn("123", self.path.read_text())

    def test_preview_repair_changes_draft_only(self):
        from service.tools import preview_service
        from service.files import tool_inputs
        draft = self.root / "draft.py"
        draft.write_text("def main(): pass\n")
        chat_id = ai_chat.get_or_create_tool_chat("demo", "example", "Example")
        token = tool_inputs.create(chat_id, "preview", [], tool_key="tool:demo/example")
        with patch.object(preview_service, "get_preview_file", return_value=draft):
            report = tool_repairs.get(tool_repairs.capture(RuntimeError(), "demo", "example", preview_key="preview", context=token))
            session = tool_repairs.RepairSession(report)
            args = {"project": "demo", "name": "example"}
            read = session.execute("read_tool", args)
            result = session.execute("write_tool", {**args, "revision": read["revision"], "content": "def main(): return 42\n"})
        self.assertTrue(result["requires_manual_run"])
        self.assertEqual('preview', result['source'])
        self.assertIn("42", draft.read_text())
        self.assertNotIn("42", self.path.read_text())


class DiagnosticTests(RepairFixture, unittest.TestCase):
    def start(self, report_id, **options):
        chat_id = tool_repairs.approve(report_id, tool_repairs.model_fingerprint(), **options)
        session = tool_repairs.RepairSession(tool_repairs.claim(chat_id))
        self.args = {'project': 'demo', 'name': 'example'}
        session.execute('read_tool', self.args)
        return session

    def test_real_log_messages_are_available_only_after_confirmation(self):
        report_id = self.report()
        session = self.start(report_id)
        info = session.execute('read_tool_logs', self.args)
        self.assertEqual('current', info['status'])
        self.assertIn('secret business body', json.dumps(info))
        self.assertNotIn('secret business body', json.dumps(tool_repairs.get(report_id)))

    def test_active_repair_cannot_save_before_reading_current_diagnostics(self):
        session = self.start(self.report())
        read = session.execute('read_tool', self.args)
        self.assertIn('error', session.execute('write_tool', {**self.args, **read}))
        self.assertEqual('current', session.execute('read_tool_logs', self.args)['status'])
        self.assertTrue(session.execute('write_tool', {**self.args, **read})['requires_manual_run'])

    def test_real_traceback_preserves_message_and_tool_line_without_locals(self):
        self.path.write_text('def main():\n    private_local = "do-not-share-local"\n    raise ValueError("runtime failure detail")\n')
        namespace = {}
        exec(compile(self.path.read_text(), str(self.path), 'exec'), namespace)
        try:
            namespace['main']()
        except ValueError as error:
            report_id = tool_repairs.capture(error, 'demo', 'example')
        info = self.start(report_id).execute('read_tool_logs', self.args)
        text = json.dumps(info)
        self.assertIn('runtime failure detail', text)
        self.assertIn('line 3', text)
        self.assertNotIn('do-not-share-local', text)

    def test_diagnostics_require_approval_read_and_exact_target(self):
        report_id = self.report()
        pending = tool_repairs.RepairSession(tool_repairs.get(report_id))
        args = {'project': 'demo', 'name': 'example'}
        self.assertIn('error', pending.execute('read_tool_logs', args))
        chat_id = tool_repairs.approve(report_id, tool_repairs.model_fingerprint())
        session = tool_repairs.RepairSession(tool_repairs.claim(chat_id))
        self.assertIn('error', session.execute('read_tool_logs', args))
        session.execute('read_tool', args)
        for parameters in ({**args, 'name': 'other'}, {**args, 'path': '/private/file'}, {**args, 'report_id': 'other'}):
            self.assertIn('error', session.execute('read_tool_logs', parameters))
        self.assertIn('error', ai_chat.execute_tool('read_tool_logs', args))

    def test_changed_code_or_new_failure_cannot_be_mistaken_for_current_error(self):
        report_id = self.report()
        session = self.start(report_id)
        self.path.write_text('def main():\n    return 42\n')
        self.assertIn('error', session.execute('read_tool_logs', self.args))
        session.execute('read_tool', self.args)
        self.assertEqual('code_changed', session.execute('read_tool_logs', self.args)['status'])
        tool_repairs.finish(report_id, False, session.report['attempt'])
        from core import tool_run_logs
        self.path.write_text('def main(): pass\n')
        run = tool_run_logs.start('demo', 'example')
        self.addCleanup(run.close)
        with run.context():
            session = self.start(self.report())
            self.report()
        self.assertEqual('superseded', session.execute('read_tool_logs', self.args)['status'])

    def test_log_search_pagination_redaction_and_snapshot(self):
        from service.tools.tool_diagnostics import log_path
        self.path.write_text('api_key = "literal-key"\ndef main(): pass\n')
        report_id = tool_repairs.capture(ValueError('api_key=hidden-key literal-key'), 'demo', 'example')
        report = tool_repairs.get(report_id)
        session = self.start(report_id)
        first = session.execute('read_tool_logs', {**self.args, 'limit': 1})
        self.assertIsNotNone(first['next_offset'])
        second = session.execute('read_tool_logs', {**self.args, 'offset': first['next_offset'], 'limit': 100})
        self.assertIn('ValueError', str(second))
        self.assertNotIn('literal-key', str(second))
        self.assertNotIn('hidden-key', str(second))
        with log_path(report).open('a') as stream:
            stream.write('later-unapproved-error\n')
        self.assertNotIn('later-unapproved-error', str(session.execute('read_tool_logs', self.args)))
        search = session.execute('read_tool_logs', {**self.args, 'query': 'ValueError'})
        self.assertEqual(1, search['matching_lines'])
        for bad in ({'offset': -1}, {'limit': 101}, {'query': 'a' * 201}):
            with self.assertRaises(ValueError):
                session.execute('read_tool_logs', {**self.args, **bad})

    def test_rotated_or_symlink_log_fails_closed(self):
        from service.tools.tool_diagnostics import log_path
        report_id = self.report()
        session = self.start(report_id)
        path = log_path(tool_repairs.get(report_id))
        path.rename(path.with_suffix('.old'))
        path.write_text('unrelated new log')
        self.assertEqual('log_changed', session.execute('read_tool_logs', self.args)['status'])
        path.unlink()
        path.symlink_to(self.path)
        with self.assertRaises(ValueError):
            session.execute('read_tool_logs', self.args)

    def test_same_file_rewrite_is_not_treated_as_approved_logs(self):
        from service.tools.tool_diagnostics import log_path
        report_id = self.report()
        session = self.start(report_id)
        path = log_path(tool_repairs.get(report_id))
        with path.open('r+b') as stream:
            stream.write(b'CHANGED')
        self.assertEqual('log_changed', session.execute('read_tool_logs', self.args)['status'])

    def test_large_logs_have_bounded_pages_and_literal_search(self):
        from service.tools.tool_diagnostics import log_path, MAX_LOG_BYTES, MAX_PAGE_CHARS
        from core import tool_run_logs
        run = tool_run_logs.start('demo', 'example')
        self.addCleanup(run.close)
        with run.context():
            path = run.path
            path.write_text('old-line\n' * 40000 + 'literal .* marker\n')
            session = self.start(self.report())
        page = session.execute('read_tool_logs', {**self.args, 'limit': 100})
        self.assertTrue(page['bounded_tail'])
        self.assertLessEqual(sum(len(row['text']) for row in page['untrusted_log_lines']), MAX_PAGE_CHARS)
        report = tool_repairs.get(session.report['id'])
        self.assertLessEqual(report['log_window']['end'] - report['log_window']['start'], MAX_LOG_BYTES)
        found = session.execute('read_tool_logs', {**self.args, 'query': '.*'})
        self.assertEqual(1, found['matching_lines'])

    def test_rotation_preserves_captured_failure_window_when_archive_exists(self):
        from core import tool_run_logs
        run = tool_run_logs.start('demo', 'example')
        self.addCleanup(run.close)
        with run.context():
            session = self.start(self.report())
        run.writer.write('later log entry' + 'x' * (tool_run_logs.MAX_RUN_BYTES // 2))
        result = session.execute('read_tool_logs', self.args)
        self.assertEqual('current', result['status'])
        self.assertIn('secret business body', str(result))
        self.assertNotIn('later log entry', str(result))

    def test_other_run_errors_and_logs_are_not_mixed_into_current_repair(self):
        from core import tool_run_logs
        first = tool_run_logs.start('demo', 'example')
        second = tool_run_logs.start('demo', 'example')
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        with first.context():
            first_id = tool_repairs.capture(ValueError('first run failure'), 'demo', 'example')
        session = self.start(first_id)
        with second.context():
            tool_repairs.capture(ValueError('second run failure'), 'demo', 'example')
        result = session.execute('read_tool_logs', self.args)
        self.assertEqual('current', result['status'])
        self.assertEqual(first.id, result['log_run_id'])
        self.assertIn('first run failure', str(result))
        self.assertNotIn('second run failure', str(result))

    def test_chat_deletion_revokes_log_access(self):
        report_id = self.report()
        session = self.start(report_id)
        ai_chat.delete_chat(session.report['chat_id'])
        with self.assertRaises(ValueError):
            session.execute('read_tool_logs', self.args)



class RepairModelTests(RepairFixture, unittest.IsolatedAsyncioTestCase):
    async def test_repair_preserves_normal_context_and_manual_preview_event(self):
        import hashlib
        chat_id = 'ui-edit-conversation'
        history = [
            {"role": "user", "content": "Keep the new blue sidebar and compact cards"},
            {"role": "assistant", "content": "The new UI has been saved."},
        ]
        ai_chat.save_chat(chat_id, history)
        revised = self.path.read_text().replace('    pass', '    layout = "new-blue-sidebar-compact-cards"\n    broken = True')
        saved = await ai_chat.execute_chat_tool('write_tool', {
            'project': 'demo', 'name': 'example', 'content': revised,
            'revision': hashlib.sha256(self.path.read_bytes()).hexdigest(),
        }, chat_id, history)
        self.assertIn('saved', saved)
        report_id = self.report()
        self.assertEqual(chat_id, tool_repairs.approve(report_id, tool_repairs.model_fingerprint()))
        report = tool_repairs.claim(chat_id)
        requests = []

        def handle(request):
            payload = json.loads(request.content)
            requests.append(payload)
            count = len(requests)
            args = {"project": "demo", "name": "example"}
            if count == 1:
                name = "read_tool"
            elif count == 2:
                name = 'read_tool_logs'
            elif count == 3:
                diagnostic = json.loads(payload['messages'][-1]['content'])
                self.assertEqual('current', diagnostic['status'])
                self.assertIn('secret business body', str(diagnostic['untrusted_log_lines']))
                read = json.loads(next(m['content'] for m in payload['messages'] if m.get('tool_call_id') == 'call1'))
                name = "write_tool"
                args.update(read)
                args['content'] = args['content'].replace('broken = True', 'broken = False')
            else:
                return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"Saved. Retry manually."}}]}\n\ndata: [DONE]\n\n')
            packet = {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": f"call{count}", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}
            return httpx.Response(200, text="data: " + json.dumps(packet) + "\n\ndata: [DONE]\n\n")

        client_class = httpx.AsyncClient
        history = ai_chat.read_chat(chat_id)
        history.append({"role": "user", "repair_id": report_id, "content": tool_repairs.request_message(report)})
        with patch.object(agent_model.httpx, "AsyncClient", side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handle))):
            events = [event async for event in ai_chat.respond(history, chat_id=chat_id, repair=report)]
        serialized = json.dumps(requests)
        self.assertIn("Keep the new blue sidebar and compact cards", serialized)
        self.assertIn("The new UI has been saved.", serialized)
        self.assertIn("secret business body", serialized)
        self.assertNotIn("private-tool-key", serialized)
        self.assertIn("read_attachment", serialized)
        self.assertIn("read_ui_reference", serialized)
        self.assertIn('read_component_api', serialized)
        self.assertTrue(any(kind == "manual_preview" for kind, _ in events))
        self.assertFalse(any(kind == "preview" for kind, _ in events))
        self.assertIn("private-tool-key", self.path.read_text())
        self.assertIn('new-blue-sidebar-compact-cards', self.path.read_text())
        self.assertIn('broken = False', self.path.read_text())
