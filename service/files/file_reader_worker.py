"""Bounded document parsing worker. JSON stdin/stdout; never executes document code."""

import csv
import io
import json
import math
import os
import stat
import sys
import zipfile
from pathlib import Path

MAX_INPUT = 50 * 1024 * 1024
MAX_EXPANDED = 200 * 1024 * 1024
MAX_TEXT = 20000


def error(code):
    return {"error": {"code": code}}


def check_archive(handle):
    with zipfile.ZipFile(handle) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED:
            raise ValueError("expanded_limit")
        expanded = 0
        for item in archive.infolist():
            if item.is_dir():
                continue
            with archive.open(item) as entry:
                while chunk := entry.read(65536):
                    expanded += len(chunk)
                    if expanded > MAX_EXPANDED:
                        raise ValueError("expanded_limit")
    handle.seek(0)


def table_result(columns, rows, offset, limit, *, known_more=False):
    columns = [str(value)[:200] if value is not None else "" for value in list(columns)[:50]]
    output = []
    budget = MAX_TEXT
    truncated_cells = False
    for row in rows:
        if len(output) >= limit:
            known_more = True
            break
        cells = []
        selected_cells = list(row)[:50]
        cell_limit = min(1000, MAX_TEXT // max(len(selected_cells), 1) // 2)
        for value in selected_cells:
            if isinstance(value, float) and not math.isfinite(value):
                value = None
            if value is not None and not isinstance(value, (int, float, bool, str)):
                value = str(value)
            if isinstance(value, str) and len(value) > cell_limit:
                value = value[:cell_limit]
                truncated_cells = True
            cells.append(value)
        cost = len(json.dumps(cells, ensure_ascii=False, default=str))
        if cost > budget:
            known_more = True
            break
        budget -= cost
        output.append(cells)
    return {"columns": columns, "rows": output, "truncated": known_more or truncated_cells,
            "cells_truncated": truncated_cells,
            "next_offset": offset + len(output) if known_more and output else None}


def parse(handle, name, *, sheet=None, offset=0, limit=20):
    extension = Path(name).suffix.lower()
    if extension == ".xlsx":
        from openpyxl import load_workbook
        check_archive(handle)
        workbook = load_workbook(handle, read_only=True, data_only=True, keep_links=False)
        try:
            if any(len(item.title) > 128 for item in workbook.worksheets):
                return error("corrupt")
            if sheet is None:
                return {"kind": "xlsx", "sheets": [{"name": item.title, "rows": item.max_row, "columns": item.max_column} for item in workbook.worksheets[:100]], "truncated": len(workbook.worksheets) > 100}
            if sheet not in workbook.sheetnames:
                return error("sheet_not_found")
            worksheet = workbook[sheet]
            columns = next(worksheet.iter_rows(min_row=1, max_row=1, max_col=min(worksheet.max_column or 1, 50), values_only=True), [])
            last_row = min(worksheet.max_row, offset + limit + 2) if worksheet.max_row is not None else offset + limit + 2
            rows = worksheet.iter_rows(min_row=offset + 2, max_row=last_row, max_col=min(worksheet.max_column or 1, 50), values_only=True) if last_row >= offset + 2 else []
            return {"kind": "xlsx", "sheet": sheet, "columns_truncated": (worksheet.max_column or 0) > 50,
                    **table_result(columns, rows, offset, limit)}
        finally:
            workbook.close()
    if extension == ".docx":
        from docx import Document
        check_archive(handle)
        document = Document(handle)
        text = "\n".join([paragraph.text for paragraph in document.paragraphs] + ["\t".join(cell.text for cell in row.cells) for table in document.tables for row in table.rows])
        return {"kind": "docx", "text": text[offset:offset + MAX_TEXT], "truncated": len(text) > offset + MAX_TEXT,
                "next_offset": offset + MAX_TEXT if len(text) > offset + MAX_TEXT else None}
    if extension == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(handle)
        if reader.is_encrypted:
            return error("encrypted")
        end = min(len(reader.pages), offset + min(limit, 5))
        text = "\n".join(reader.pages[index].extract_text() or "" for index in range(offset, end))
        if not text.strip() and offset < len(reader.pages):
            return error("ocr_required")
        return {"kind": "pdf", "pages": len(reader.pages), "start_page": offset + 1, "text": text[:MAX_TEXT],
                "truncated": end < len(reader.pages) or len(text) > MAX_TEXT, "next_offset": end if end < len(reader.pages) else None}
    if extension not in {".txt", ".md", ".log", ".json", ".yaml", ".yml", ".xml", ".csv", ".tsv"}:
        return error("unsupported")
    text = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
    try:
        if extension in {".csv", ".tsv"}:
            csv.field_size_limit(1024 * 1024)
            reader = csv.reader(text, delimiter="\t" if extension == ".tsv" else ",")
            columns = next(reader, [])
            for _ in range(offset):
                if next(reader, None) is None:
                    break
            return {"kind": "csv", "columns_truncated": len(columns) > 50, **table_result(columns, reader, offset, limit)}
        text.read(offset)
        content = text.read(MAX_TEXT + 1)
        return {"kind": "text", "text": content[:MAX_TEXT], "truncated": len(content) > MAX_TEXT,
                "next_offset": offset + MAX_TEXT if len(content) > MAX_TEXT else None}
    finally:
        text.detach()


def read_request(request):
    record = request["record"]
    try:
        with open(record["original_path"], "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                return error("unsupported")
            expected = (record["size"], record["mtime_ns"], record["device"], record["inode"])
            if (info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino) != expected or str(Path(record["original_path"]).resolve()) != record["path"]:
                return error("changed")
            if info.st_size > MAX_INPUT:
                return error("input_limit")
            result = parse(handle, record["name"], **request["options"])
            after = os.fstat(handle.fileno())
            if (after.st_size, after.st_mtime_ns, after.st_dev, after.st_ino) != expected:
                return error("changed")
            return result
    except PermissionError:
        return error("denied")
    except FileNotFoundError:
        return error("missing")
    except UnicodeError:
        return error("encoding")
    except ValueError as exception:
        return error("expanded_limit" if str(exception) == "expanded_limit" else "corrupt")
    except Exception:  # noqa: BLE001 - worker boundary maps parser-specific exceptions without leaking file data
        return error("corrupt")


def main():
    result = read_request(json.loads(sys.stdin.read(65536)))
    print(json.dumps(result, ensure_ascii=False, default=str, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
