"""
project: acceptance
name: office_excel
description: Synthetic workbook interaction fixture; not installed in user tools
creator: acceptance-tests
created_at: 2026-10-21
updated_at: 2026-10-21
tags: Excel,测试
"""

import logging
import math
from collections import defaultdict
from pathlib import Path

from nicegui import run, ui
from openpyxl import Workbook, load_workbook

from component.tool_files import ToolFileInput
from component.tool_results import ToolResults

logger = logging.getLogger(__name__)


def read_book(path: str) -> dict:
    """Bound the fixture workload and reject ambiguous headers."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheets = {}
        remaining = 10000
        for sheet in workbook:
            rows = sheet.iter_rows(values_only=True)
            header = tuple(str(value or "").strip() for value in next(rows, ()))
            if not header or not all(header) or len(set(header)) != len(header):
                raise ValueError("Invalid column names")
            data = []
            for row in rows:
                remaining -= 1
                if remaining < 0:
                    raise ValueError("Fixture supports at most 10000 rows")
                if any(value is not None for value in row):
                    data.append(tuple(row))
            sheets[sheet.title] = (header, data)
        return sheets
    finally:
        workbook.close()


def summarize(data: tuple, group: str, amount: str, match: str) -> list[dict]:
    header, rows = data
    group_index, amount_index = header.index(group), header.index(amount)
    totals = defaultdict(float)
    for row in rows:
        label = str(row[group_index] or "(empty)")
        if match.strip().casefold() not in label.casefold():
            continue
        value = row[amount_index]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Choose a numeric column")
        totals[label] += value
    return [{"group": key, "total": value} for key, value in sorted(totals.items())]


def write_report(path: Path, rows: tuple) -> None:
    workbook = Workbook()
    try:
        workbook.active.append(["Group", "Total"])
        for group, total in rows:
            # Treat spreadsheet formula-like labels as text, not formulas.
            cell = workbook.active.cell(workbook.active.max_row + 1, 1, group)
            cell.data_type = "s"
            workbook.active.cell(cell.row, 2, total)
        workbook.save(path)
    finally:
        workbook.close()


def main() -> None:
    sheets, report = {}, []
    busy = False
    with ui.column().classes("w-full min-w-0 gap-3"):
        inputs = ToolFileInput()
        read = ui.button("读取工作簿", icon="folder_open").props("dense no-caps")
        with ui.element("div").classes("grid grid-cols-1 md:grid-cols-3 gap-3 w-full min-w-0"):
            sheet = ui.select([], label="工作表").props("outlined dense hide-bottom-space")
            group = ui.select([], label="分组字段").props("outlined dense hide-bottom-space")
            amount = ui.select([], label="数值字段").props("outlined dense hide-bottom-space")
        with ui.row().classes("w-full min-w-0 items-center gap-2 flex-wrap"):
            match = ui.input("分组包含").props("outlined dense hide-bottom-space").classes("flex-1 min-w-0")
            analyze = ui.button("汇总", icon="bar_chart").props("dense no-caps")
            export = ui.button("导出结果", icon="download").props("flat dense no-caps")
        status = ui.label("请选择一个 XLSX 文件").classes("text-sm text-gray-500")
        chart = ui.echart({"xAxis": {"type": "category", "data": []}, "yAxis": {"type": "value"}, "series": [{"type": "bar", "data": []}]}).classes("w-full h-64 min-w-0")
        table = ui.table(columns=[{"name": key, "label": label, "field": key} for key, label in [("group", "分组"), ("total", "合计")]], rows=[], row_key="group", pagination=10).props("flat dense").classes("w-full min-w-0")
        results = ToolResults()

    def controls() -> None:
        inputs.set_enabled(not busy)
        read.set_enabled(not busy)
        for control in (sheet, group, amount, match, analyze):
            control.set_enabled(not busy and bool(sheets))
        export.set_enabled(not busy and bool(report))

    def invalidate() -> None:
        report.clear()
        table.rows = []
        table.update()
        chart.options["xAxis"]["data"] = []
        chart.options["series"][0]["data"] = []
        chart.update()
        controls()

    def select_sheet() -> None:
        invalidate()
        header = sheets[sheet.value][0] if sheet.value in sheets else []
        group.set_options(list(header), value=header[0] if header else None)
        amount.set_options(list(header), value=header[-1] if header else None)

    async def load() -> None:
        nonlocal busy
        if busy:
            return
        busy = True
        controls()
        try:
            paths = inputs.freeze()
            if len(paths) != 1 or Path(paths[0]).suffix.lower() != ".xlsx":
                raise ValueError("Select one XLSX")
            sheets.clear()
            invalidate()
            sheets.update(await run.io_bound(read_book, paths[0]))
            sheet.set_options(list(sheets), value=next(iter(sheets), None))
            select_sheet()
            status.set_text(f"已读取 {len(sheets)} 个工作表")
        except Exception:
            sheets.clear()
            sheet.set_options([], value=None)
            select_sheet()
            status.set_text("读取失败，请选择有效的 XLSX 文件并检查访问权限")
            logger.exception("Fixture workbook read failed")
        finally:
            busy = False
            controls()

    async def aggregate() -> None:
        nonlocal busy
        if busy or sheet.value not in sheets:
            return
        busy = True
        controls()
        try:
            rows = await run.io_bound(summarize, sheets[sheet.value], group.value, amount.value, match.value or "")
            report[:] = rows
            table.rows = rows
            table.update()
            chart.options["xAxis"]["data"] = [row["group"] for row in rows]
            chart.options["series"][0]["data"] = [row["total"] for row in rows]
            chart.update()
            status.set_text(f"汇总完成：{len(rows)} 组" if rows else "没有匹配的分组")
        except Exception:
            invalidate()
            status.set_text("汇总失败，请选择数值字段")
            logger.exception("Fixture aggregation failed")
        finally:
            busy = False
            controls()

    async def save() -> None:
        nonlocal busy
        if busy or not report:
            return
        rows = tuple((row["group"], row["total"]) for row in report)
        busy = True
        controls()
        try:
            results.start_run()
            await run.io_bound(results.outputs.write, "summary.xlsx", lambda path: write_report(path, rows))
            results.refresh()
            status.set_text("结果已导出")
        except Exception:
            status.set_text("导出失败，请重试")
            logger.exception("Fixture export failed")
        finally:
            busy = False
            controls()

    read.on_click(load)
    analyze.on_click(aggregate)
    export.on_click(save)
    sheet.on_value_change(select_sheet)
    for control in (group, amount, match):
        control.on_value_change(invalidate)
    controls()


if __name__ in {"__main__", "__mp_main__"}:
    main()
    ui.run(title="Office acceptance", show=False)
