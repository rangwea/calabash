"""Synthetic tool-owned office processing in the frozen runtime, without Actions."""
import io
import json
import time
import urllib.request

BACKEND = '''

def install_office_smoke(app, sdk):
    @app.post('/api/office-smoke', operation_id='office_smoke')
    async def office_smoke() -> dict[str, str]:
        def process():
            import sys
            def phase(name):
                print("Synthetic office smoke: " + name, file=sys.stderr, flush=True)
            phase("loading openpyxl")
            from openpyxl import Workbook, load_workbook
            phase("openpyxl loaded; loading docx")
            from docx import Document
            phase("creating spreadsheet")
            spreadsheet = sdk.output_path('synthetic.xlsx')
            book = Workbook()
            book.active.append(['编号', '客户'])
            book.active.append(['001', '合成客户'])
            book.save(spreadsheet)
            phase("reading spreadsheet")
            restored = load_workbook(spreadsheet)
            row = list(restored.active.values)[1]
            restored.close()
            phase("creating document")
            document = sdk.output_path('synthetic.docx')
            doc = Document()
            doc.add_paragraph(f'{row[1]}：{row[0]}')
            doc.save(document)
            phase("processing complete")
            return spreadsheet, document
        import faulthandler
        # Synthetic acceptance only: never enable thread dumps for user tools.
        faulthandler.dump_traceback_later(30, repeat=False)
        try:
            spreadsheet, document = await sdk.io(process)
        finally:
            faulthandler.cancel_dump_traceback_later()
        return {'excel': sdk.add_result(spreadsheet)['id'], 'word': sdk.add_result(document)['id']}
'''


def verify(origin, token):
    from docx import Document
    from openpyxl import load_workbook
    headers = {'Authorization': 'Bearer ' + token}
    request = urllib.request.Request(origin + '/api/office-smoke', data=b'', headers=headers)
    # Frozen Windows libraries can incur a cold-load/antivirus scan on first use.
    # Keep one bounded attempt; never retry an operation that may have written files.
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=90) as response:
        files = json.load(response)
    print(f'Installed office processing completed in {time.monotonic() - started:.1f}s', flush=True)
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
