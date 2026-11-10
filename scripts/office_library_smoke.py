"""Synthetic tool-owned office processing in the frozen runtime, without Actions."""
import io
import json
import urllib.request

BACKEND = '''

def install_office_smoke(app, sdk):
    @app.post('/api/office-smoke', operation_id='office_smoke')
    async def office_smoke() -> dict[str, str]:
        def process():
            from openpyxl import Workbook, load_workbook
            from docx import Document
            spreadsheet = sdk.output_path('synthetic.xlsx')
            book = Workbook()
            book.active.append(['编号', '客户'])
            book.active.append(['001', '合成客户'])
            book.save(spreadsheet)
            restored = load_workbook(spreadsheet)
            row = list(restored.active.values)[1]
            restored.close()
            document = sdk.output_path('synthetic.docx')
            doc = Document()
            doc.add_paragraph(f'{row[1]}：{row[0]}')
            doc.save(document)
            return spreadsheet, document
        spreadsheet, document = await sdk.io(process)
        return {'excel': sdk.add_result(spreadsheet)['id'], 'word': sdk.add_result(document)['id']}
'''


def verify(origin, token):
    from docx import Document
    from openpyxl import load_workbook
    headers = {'Authorization': 'Bearer ' + token}
    request = urllib.request.Request(origin + '/api/office-smoke', data=b'', headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        files = json.load(response)
    outputs = {}
    for kind, identity in files.items():
        with urllib.request.urlopen(urllib.request.Request(origin + '/api/sdk/results/' + identity, headers=headers), timeout=10) as response:
            outputs[kind] = response.read()
    book = load_workbook(io.BytesIO(outputs['excel']))
    try:
        assert list(book.active.values) == [('编号', '客户'), ('001', '合成客户')]
    finally:
        book.close()
    assert Document(io.BytesIO(outputs['word'])).paragraphs[0].text == '合成客户：001'
