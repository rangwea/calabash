"""Synthetic office acceptance: typed discovery, immutable inputs, real output files."""
import asyncio
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import httpx
from docx import Document
from fastapi import FastAPI, UploadFile
from openpyxl import Workbook, load_workbook

from service.actions.office import ActionFailure
from service.actions.registry import describe
from service.tools.tool_sdk import ToolSDK


def workbook(rows):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def document():
    doc = Document()
    paragraph = doc.add_paragraph()
    paragraph.add_run('客户：').bold = True
    paragraph.add_run('{{客').italic = True
    paragraph.add_run('户}} / {{编号}}')
    doc.add_table(rows=1, cols=1).cell(0, 0).text = '{{客户}}'
    doc.sections[0].header.paragraphs[0].text = '{{编号}}'
    doc.sections[0].footer.paragraphs[0].text = '{{客户}}'
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


class OfficeActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {'HOME': temporary.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.sdk = ToolSDK('demo', 'office')
        self.sdk.loop = asyncio.get_running_loop()

    async def select(self, name, content):
        return (await self.sdk.upload_input(UploadFile(io.BytesIO(content), filename=name)))['id']

    async def complete(self):
        await self.sdk.task
        return self.sdk.actions.runs()

    async def test_excel_merge_clean_deduplicate_export_and_source_unchanged(self):
        a = await self.select('a.xlsx', workbook([['编号', '客户'], [' A ', ' 张三 '], [None, None], ['B', '李四']]))
        b = await self.select('b.xlsx', workbook([['编号', '客户', '金额'], ['A', '张三', 20], ['C', '王五', 30]]))
        before = {identity: self.sdk.input_path(identity).read_bytes() for identity in (a, b)}
        self.sdk.actions.start('office.excel.process', {'input_ids': [a, b], 'rename_columns': {'客户': '姓名'}, 'deduplicate_by': ['编号']})
        result = (await self.complete())[0]
        self.assertEqual('succeeded', result['status'], result)
        self.assertEqual({'read_rows': 5, 'written_rows': 3, 'empty_rows': 1, 'duplicate_rows': 1}, result['result']['counts'])
        path = self.sdk.outputs.path(result['result']['outputs'][0]['id'])
        book = load_workbook(path)
        self.assertEqual([('编号', '姓名', '金额'), ('A', '张三', None), ('B', '李四', None), ('C', '王五', 30)], list(book.active.values))
        book.close()
        for identity, content in before.items():
            self.assertEqual(content, self.sdk.input_path(identity).read_bytes())
        restored = ToolSDK('demo', 'office')
        self.assertEqual(1, len(restored.results()))
        self.assertEqual([], restored.actions.runs())

    async def test_word_split_runs_table_header_footer_and_literal_values(self):
        template = await self.select('template.docx', document())
        original = self.sdk.input_path(template).read_bytes()
        self.sdk.actions.start('office.word.fill_template', {'template_id': template, 'values': {'客户': '{{literal}}', '编号': '001'}})
        result = (await self.complete())[0]
        self.assertEqual('succeeded', result['status'], result)
        path = self.sdk.outputs.path(result['result']['outputs'][0]['id'])
        doc = Document(path)
        self.assertEqual('客户：{{literal}} / 001', doc.paragraphs[0].text)
        self.assertTrue(doc.paragraphs[0].runs[0].bold)
        self.assertTrue(doc.paragraphs[0].runs[1].italic)
        self.assertEqual('{{literal}}', doc.tables[0].cell(0, 0).text)
        self.assertEqual('001', doc.sections[0].header.paragraphs[0].text)
        self.assertEqual('{{literal}}', doc.sections[0].footer.paragraphs[0].text)
        self.assertEqual(5, result['result']['counts']['replacements'])
        self.assertEqual(original, self.sdk.input_path(template).read_bytes())

    async def test_failure_does_not_publish_partial_results_or_log_values(self):
        identity = await self.select('formula.xlsx', workbook([['值'], ['=1+2']]))
        self.sdk.actions.start('office.excel.process', {'input_ids': [identity]})
        result = (await self.complete())[0]
        self.assertEqual('failed', result['status'])
        self.assertEqual('formulas_or_errors_unsupported', result['error']['code'])
        self.assertEqual([], self.sdk.results())
        template = await self.select('private.docx', document())
        self.sdk.actions.start('office.word.fill_template', {'template_id': template, 'values': {'客户': 'private-business-content'}})
        result = (await self.complete())[0]
        self.assertEqual('missing_template_value', result['error']['code'])
        self.assertNotIn('private-business-content', json.dumps(result))
        self.assertEqual([], self.sdk.results())

    async def test_literal_formula_text_is_not_executed_in_output(self):
        book = Workbook()
        book.active.append(['text'])
        book.active.append(['=SUM(1,2)'])
        book.active['A2'].data_type = 's'
        stream = io.BytesIO()
        book.save(stream)
        identity = await self.select('literal.xlsx', stream.getvalue())
        self.sdk.actions.start('office.excel.process', {'input_ids': [identity]})
        result = (await self.complete())[0]['result']
        output = load_workbook(self.sdk.outputs.path(result['outputs'][0]['id']))
        self.assertEqual('s', output.active['A2'].data_type)
        self.assertEqual('=SUM(1,2)', output.active['A2'].value)
        output.close()

    async def test_parser_failures_log_metadata_without_business_values(self):
        from core.logger import logger
        records = io.StringIO()
        sink = logger.add(records, diagnose=False)
        try:
            identity = await self.select('private.docx', document())
            self.sdk.actions.start('office.word.fill_template', {'template_id': identity, 'values': {'客户': 'private-business-content'}})
            await self.complete()
        finally:
            logger.remove(sink)
        self.assertIn('missing_template_value', records.getvalue())
        self.assertNotIn('private-business-content', records.getvalue())
        self.assertNotIn('private.docx', records.getvalue())

    async def test_excel_output_can_supply_word_batch_values(self):
        source = await self.select('customers.xlsx', workbook([['客户', '编号'], ['合成甲', '001'], ['合成乙', '002']]))
        self.sdk.actions.start('office.excel.process', {'input_ids': [source]})
        result = (await self.complete())[0]['result']
        output = load_workbook(self.sdk.outputs.path(result['outputs'][0]['id']))
        rows = list(output.active.values)
        output.close()
        template = await self.select('template.docx', document())
        self.sdk.actions.start_batch('office.word.fill_template', [{'template_id': template, 'values': dict(zip(rows[0], row)), 'output_name': f'record-{index}.docx'} for index, row in enumerate(rows[1:])])
        results = await self.complete()
        self.assertEqual(['succeeded', 'succeeded'], [item['status'] for item in results])
        for index, item in enumerate(results):
            filled = Document(self.sdk.outputs.path(item['result']['outputs'][0]['id']))
            self.assertIn(rows[index + 1][0], filled.paragraphs[0].text)

    async def test_protocol_validation_no_paths_unknown_versions_or_extra_fields(self):
        for action, args, options in [
            ('missing', {}, {}), ('office.excel.process', {}, {'action_version': 2}),
            ('office.excel.process', {'input_ids': ['/etc/passwd']}, {}),
            ('office.excel.process', {'input_ids': ['x'], 'output_name': '../out.xlsx'}, {}),
            ('office.word.fill_template', {'template_id': 'x', 'values': {}, 'surprise': True}, {}),
        ]:
            with self.subTest(action=action, args=args), self.assertRaises(ActionFailure):
                self.sdk.actions.start(action, args, **options)
        self.assertEqual([], self.sdk.actions.runs())

    async def test_cancellation_finishes_current_output_and_stops_later_documents(self):
        template = await self.select('template.docx', document())
        entered, finish = asyncio.Event(), asyncio.Event()
        original = self.sdk.io
        async def delayed(function, *args, **kwargs):
            entered.set()
            await finish.wait()
            return await original(function, *args, **kwargs)
        with patch.object(self.sdk, 'io', delayed):
            self.sdk.actions.start_batch('office.word.fill_template', [
                {'template_id': template, 'values': {'客户': name, '编号': '1'}} for name in ('A', 'B')])
            await entered.wait()
            self.sdk.cancel()
            finish.set()
            result = await self.complete()
        self.assertEqual(['succeeded', 'cancelled'], [item['status'] for item in result])
        self.assertEqual(1, len(self.sdk.results()))

    async def test_http_discovery_submission_and_current_batch_status(self):
        app = FastAPI()
        app.include_router(self.sdk.router, prefix='/api/sdk')
        identity = await self.select('source.xlsx', workbook([['id'], [1]]))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            catalog = (await client.get('/api/sdk/actions')).json()
            self.assertEqual(2, len(catalog['actions']))
            self.assertFalse(catalog['actions'][0]['network'])
            schema = (await client.get('/api/sdk/actions/office.excel.process')).json()
            self.assertIn('input_ids', schema['input_schema']['properties'])
            self.assertEqual(422, (await client.post('/api/sdk/actions/office.excel.process', json={'protocol_version': 2, 'parameters': {}})).status_code)
            response = await client.post('/api/sdk/actions/office.excel.process', json={'parameters': {'input_ids': [identity]}})
            self.assertEqual(200, response.status_code, response.text)
            await self.complete()
            self.assertEqual('succeeded', (await client.get('/api/sdk/action-runs')).json()[0]['status'])

    async def test_agent_can_discover_but_cannot_execute_actions(self):
        from service.tools.harness_workspace import agent_call
        catalog = await agent_call('synthetic', 'lookup', 'read_action_api', {})
        self.assertEqual(2, len(catalog['actions']))
        specification = await agent_call('synthetic', 'detail', 'read_action_api', {'action_id': 'office.word.fill_template'})
        self.assertEqual(describe('office.word.fill_template'), specification)
        self.assertFalse(self.sdk.status()['running'])
        with self.assertRaises(ValueError):
            await agent_call('synthetic', 'denied', 'run_action', {'project': 'demo', 'name': 'office'})


class OfficeActionBuildTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {'HOME': temporary.name})
        environment.start()
        self.addCleanup(environment.stop)

    async def test_both_office_scenes_compile_and_wrong_action_parameters_fail(self):
        from service.tools.tool_workers import FrontendBuildError, build_bundle
        from tests.fixtures.office_actions import fixture
        for kind in ('excel', 'word'):
            built = await build_bundle(fixture(kind))
            self.assertTrue((built / 'dist/index.html').is_file())
        files = fixture('word')
        files['frontend/App.tsx'] = files['frontend/App.tsx'].replace('values: {客户: "合成客户", 编号: "001"}', 'values: {客户: 123}')
        with self.assertRaises(FrontendBuildError) as caught:
            await build_bundle(files)
        self.assertTrue(any(item.get('code') == 'TS2322' for item in caught.exception.diagnostics), caught.exception.diagnostics)

    async def test_real_worker_auth_and_action_result_download(self):
        from pathlib import Path

        from backend.tool_worker import create_tool_app
        from tests.fixtures.office_actions import fixture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, content in fixture('excel').items():
                file = root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(content)
            app = create_tool_app({'root': str(root), 'project': 'demo', 'name': 'office_excel', 'port': 12345, 'origin': 'http://127.0.0.1:12345', 'token': 'synthetic-token'})
            async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:12345') as client:
                self.assertEqual(403, (await client.get('/api/sdk/actions')).status_code)
                client.headers['Authorization'] = 'Bearer synthetic-token'
                self.assertEqual(403, (await client.get('/api/sdk/actions', headers={'Origin': 'http://foreign.invalid'})).status_code)
                uploaded = await client.post('/api/sdk/inputs', files={'file': ('source.xlsx', workbook([['id'], [1], [1]]))})
                started = await client.post('/api/sdk/actions/office.excel.process', json={'parameters': {'input_ids': [uploaded.json()['id']], 'deduplicate_by': ['id']}})
                self.assertEqual(200, started.status_code, started.text)
                async with asyncio.timeout(5):
                    while (await client.get('/api/sdk/status')).json()['running']:
                        await asyncio.sleep(.01)
                result = (await client.get('/api/sdk/action-runs')).json()[0]
                self.assertEqual('succeeded', result['status'], result)
                file_id = result['result']['outputs'][0]['id']
                downloaded = await client.get('/api/sdk/results/' + file_id)
                book = load_workbook(io.BytesIO(downloaded.content))
                self.assertEqual([('id',), (1,)], list(book.active.values))
                book.close()
