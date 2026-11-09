"""Deterministic file transformations. No source overwrite, formulas or template code."""
import re
from zipfile import BadZipFile, ZipFile

MESSAGES = {
    'unknown_action': '当前处理能力不可用，请选择其他操作',
    'unsupported_action_version': '当前处理能力版本不可用，请重新打开工具',
    'invalid_parameters': '请检查处理选项后重试',
    'input_unavailable': '所选文件已变化或不可用，请重新选择',
    'unsupported_format': '请选择支持格式的文件后重试',
    'file_limit_exceeded': '文件超出本次处理范围，请拆分后重试',
    'invalid_document': '无法读取所选文件，请确认文件完整后重试',
    'sheet_unavailable': '所选工作表不存在，请检查后重试',
    'invalid_headers': '请检查表格首行，列名不能为空或重复',
    'duplicate_headers': '请检查表格首行，列名不能为空或重复',
    'column_unavailable': '请选择表格中实际存在的列后重试',
    'formulas_or_errors_unsupported': '当前数据处理不支持公式或错误单元格，请先转换为数值',
    'invalid_template': '模板标记无法识别，请使用“{{字段名}}”格式',
    'missing_template_value': '请补全模板字段对应的内容后重试',
    'processing_failed': '工具暂时未能完成操作，请重试或让 AI 帮你修复',
}


class ActionFailure(ValueError):
    def __init__(self, code):
        self.code = code if code in MESSAGES else 'processing_failed'
        from core.i18n import t
        super().__init__(t(MESSAGES[self.code]))


def check_archive(path, extension):
    if path.suffix.lower() != extension:
        raise ActionFailure('unsupported_format')
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(item.file_size for item in entries) > 64 * 1024 * 1024 or any(item.flag_bits & 1 for item in entries):
                raise ActionFailure('file_limit_exceeded')
    except BadZipFile:
        raise ActionFailure('invalid_document') from None


def excel_process(paths, params, destination, progress):
    from openpyxl import Workbook, load_workbook
    headers, rows, original_headers = [], [], set()
    read_rows = empty_rows = cells = 0
    for index, path in enumerate(paths):
        check_archive(path, '.xlsx')
        book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
        try:
            if params.sheet is not None and params.sheet not in book.sheetnames:
                raise ActionFailure('sheet_unavailable')
            sheet = book[params.sheet] if params.sheet is not None else book.worksheets[0]
            if sheet.max_column and sheet.max_column > 200:
                raise ActionFailure('file_limit_exceeded')
            iterator = sheet.iter_rows()
            first = next(iterator, ())
            if any(cell.data_type in {'f', 'e'} for cell in first):
                raise ActionFailure('formulas_or_errors_unsupported')
            names = [cell.value.strip() if isinstance(cell.value, str) else cell.value for cell in first]
            if not names or any(not isinstance(name, str) or not name or len(name) > 200 for name in names) or len(set(names)) != len(names):
                raise ActionFailure('invalid_headers')
            original_headers.update(names)
            renamed = [params.rename_columns.get(name, name) for name in names]
            if len(set(renamed)) != len(renamed):
                raise ActionFailure('duplicate_headers')
            for name in renamed:
                if name not in headers:
                    headers.append(name)
            if len(headers) > 200:
                raise ActionFailure('file_limit_exceeded')
            for source in iterator:
                read_rows += 1
                cells += len(source)
                if read_rows > 20000 or cells > 500000:
                    raise ActionFailure('file_limit_exceeded')
                if any(cell.data_type in {'f', 'e'} for cell in source):
                    raise ActionFailure('formulas_or_errors_unsupported')
                values = [cell.value.strip() if params.strip_text and isinstance(cell.value, str) else cell.value for cell in source]
                if params.drop_empty_rows and all(value is None or value == '' for value in values):
                    empty_rows += 1
                    continue
                rows.append(dict(zip(renamed, values)))
        finally:
            book.close()
        progress((index + 1) / (len(paths) + 1))
    if not set(params.rename_columns) <= original_headers:
        raise ActionFailure('column_unavailable')
    columns = params.columns or headers
    if not set(columns) <= set(headers) or not set(params.deduplicate_by) <= set(columns):
        raise ActionFailure('column_unavailable')
    book = Workbook(write_only=True)
    sheet = book.create_sheet('Data')
    # Explicit string cell types prevent text such as '=...' becoming executable formulas.
    from openpyxl.cell import WriteOnlyCell
    def append(values):
        output = []
        for value in values:
            cell = WriteOnlyCell(sheet, value=value)
            if isinstance(value, str):
                cell.data_type = 's'
            output.append(cell)
        sheet.append(output)
    seen, duplicates, written = set(), 0, 0
    try:
        append(columns)
        for row in rows:
            if params.deduplicate_by:
                key = tuple(row.get(name) for name in params.deduplicate_by)
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
            append([row.get(name) for name in columns])
            written += 1
        book.save(destination)
    finally:
        book.close()
    return {'read_rows': read_rows, 'written_rows': written, 'empty_rows': empty_rows, 'duplicate_rows': duplicates}


def word_fill(paths, params, destination, progress):
    from docx import Document
    from docx.oxml.ns import qn
    check_archive(paths[0], '.docx')
    document = Document(paths[0])
    edits, characters, replacements = [], 0, 0
    # Body, nested tables and existing headers/footers; never evaluate expressions.
    for part in document.part.package.parts:
        element = getattr(part, '_element', None)
        if element is None or element.tag not in {qn('w:document'), qn('w:hdr'), qn('w:ftr')}:
            continue
        for paragraph in element.iter(qn('w:p')):
            nodes, chunks = [], []
            for node in paragraph.iter():
                if node.tag not in {qn('w:t'), qn('w:tab'), qn('w:br')}:
                    continue
                ancestor = node.getparent()
                while ancestor is not None and ancestor.tag != qn('w:p'):
                    ancestor = ancestor.getparent()
                if ancestor is not paragraph:
                    continue
                nodes.append(node)
                chunks.append(node.text or '' if node.tag == qn('w:t') else '\n')
            text = ''.join(chunks)
            characters += len(text)
            if characters > 1000000:
                raise ActionFailure('file_limit_exceeded')
            matches = list(re.finditer(r'\{\{([^{}]*)\}\}', text))
            residue = re.sub(r'\{\{[^{}]*\}\}', '', text)
            if '{{' in residue or '}}' in residue:
                raise ActionFailure('invalid_template')
            for match in matches:
                field = re.fullmatch(r' *([\w.-]{1,80}) *', match[1])
                if not field:
                    raise ActionFailure('invalid_template')
                if field[1] not in params.values:
                    raise ActionFailure('missing_template_value')
                replacements += 1
                if replacements > 10000:
                    raise ActionFailure('file_limit_exceeded')
            edits.append((nodes, chunks, matches))
    for nodes, chunks, matches in edits:
        offsets, end = [], 0
        for chunk in chunks:
            offsets.append((end, end + len(chunk)))
            end += len(chunk)
        for match in reversed(matches):
            value = params.values[match[1].strip()]
            first = True
            for index, (start, stop) in enumerate(offsets):
                if start < match.end() and stop > match.start():
                    left, right = max(0, match.start() - start), min(len(chunks[index]), match.end() - start)
                    chunks[index] = chunks[index][:left] + (value if first else '') + chunks[index][right:]
                    first = False
        for node, text in zip(nodes, chunks):
            if node.tag == qn('w:t'):
                node.text = text
                node.set(qn('xml:space'), 'preserve')
    document.save(destination)
    progress(1)
    return {'documents': 1, 'replacements': replacements}
