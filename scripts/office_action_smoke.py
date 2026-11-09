"""Synthetic installed-runtime acceptance for the two built-in office actions."""
import io
import json
import time
import urllib.request
from uuid import uuid4


def verify(origin, token):
    from docx import Document
    from openpyxl import Workbook, load_workbook
    headers = {'Authorization': 'Bearer ' + token}

    def request(path, data=None, content_type='application/json'):
        options = dict(headers)
        if data is not None:
            options['Content-Type'] = content_type
        return urllib.request.urlopen(urllib.request.Request(origin + '/api/sdk' + path, data=data, headers=options), timeout=10)

    def upload(name, content):
        boundary = uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
                + content + f'\r\n--{boundary}--\r\n'.encode())
        with request('/inputs', body, 'multipart/form-data; boundary=' + boundary) as response:
            return json.load(response)['id']

    def run(action, parameters):
        with request('/actions/' + action, json.dumps({'protocol_version': 1, 'action_version': 1, 'parameters': parameters}).encode()) as response:
            json.load(response)
        deadline = time.monotonic() + 15
        while True:
            with request('/status') as response:
                running = json.load(response)['running']
            if not running:
                break
            if time.monotonic() > deadline:
                raise TimeoutError('Office action')
            time.sleep(.05)
        with request('/action-runs') as response:
            result = json.load(response)[0]
        assert result['status'] == 'succeeded', result
        with request('/results/' + result['result']['outputs'][0]['id']) as response:
            return response.read()

    book = Workbook()
    book.active.append(['编号', '客户'])
    book.active.append(['001', ' 合成客户 '])
    book.active.append(['001', '重复'])
    source = io.BytesIO()
    book.save(source)
    identity = upload('customers.xlsx', source.getvalue())
    result = run('office.excel.process', {'input_ids': [identity], 'deduplicate_by': ['编号']})
    output = load_workbook(io.BytesIO(result))
    rows = list(output.active.values)
    output.close()
    assert rows == [('编号', '客户'), ('001', '合成客户')], rows
    template = Document()
    paragraph = template.add_paragraph()
    paragraph.add_run('{{客')
    paragraph.add_run('户}}：{{编号}}')
    source = io.BytesIO()
    template.save(source)
    identity = upload('template.docx', source.getvalue())
    result = run('office.word.fill_template', {'template_id': identity, 'values': dict(zip(rows[0], rows[1]))})
    assert Document(io.BytesIO(result)).paragraphs[0].text == '合成客户：001'
