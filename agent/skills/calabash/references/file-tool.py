"""
project: calabash
name: csv_file_tool_template
description: CSV 批量清理示例：文件输入、安全导出、结果历史、取消与失败重试
creator: auto-generator
created_at: 2026-10-19
updated_at: 2026-10-19
tags: 文件处理,批量任务,导出
requires:
"""

import csv
import logging
from pathlib import Path

from nicegui import run, ui

from component.tool_files import ToolFileInput
from component.tool_results import ToolJobStatus, ToolResults
from service.tools.tool_jobs import ToolJobs

logger = logging.getLogger(__name__)


def export_csv(source: Path, destination: Path, drop_blank: bool) -> None:
    """Stream UTF-8 CSV rows to the private destination; never write to source."""
    if source.suffix.lower() != ".csv":
        raise ValueError("Unsupported input format")
    before = source.stat()
    with source.open(encoding="utf-8-sig", newline="") as incoming, destination.open("w", encoding="utf-8-sig", newline="") as outgoing:
        reader = csv.DictReader(incoming)
        if not reader.fieldnames:
            raise ValueError("CSV header is missing")
        writer = csv.DictWriter(outgoing, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            if drop_blank and not any(str(value or "").strip() for value in row.values()):
                continue
            writer.writerow(row)
    after = source.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("Input changed during processing")


def main() -> None:
    ui.page_title("CSV 批量清理")
    jobs: ToolJobs | None = None
    with ui.column().classes("w-full gap-3"):
        inputs = ToolFileInput()
        with ui.row().classes("w-full items-center gap-3 flex-wrap"):
            drop_blank = ui.switch("删除空行", value=True).props("dense")
            start = ui.button("开始处理", icon="play_arrow").props("dense no-caps").classes("file-tool-start")
        summary = ui.label("尚未运行").classes("text-sm text-gray-500")
        error = ui.label("部分文件处理失败，请检查 CSV 格式和访问权限后重试。").classes("text-sm text-negative")
        error.set_visibility(False)
        status_area = ui.column().classes("w-full gap-2")
        ui.separator()
        ui.label("结果文件").classes("text-sm font-semibold")
        results = ToolResults()

    class BatchStatus(ToolJobStatus):
        def refresh(self) -> None:
            super().refresh()
            states = [job.status for job in self.jobs.jobs]
            summary.set_text(f"完成 {states.count('succeeded')} · 失败 {states.count('failed')} · 取消 {states.count('cancelled')}")
            error.set_visibility("failed" in states)
            start.set_enabled(not self.jobs.running)
            drop_blank.set_enabled(not self.jobs.running)
            inputs.set_enabled(not self.jobs.running)

    async def submit() -> None:
        nonlocal jobs
        if jobs and jobs.running:
            return
        try:
            paths = inputs.freeze()
        except ValueError:
            ui.notify("文件已变化或不可访问，请重新选择", type="warning")
            return
        if not paths:
            inputs.unfreeze()
            ui.notify("请先选择 CSV 文件", type="warning")
            return
        try:
            remove_blank = bool(drop_blank.value)
            results.start_run()
            jobs = ToolJobs(paths)
            status_area.clear()
            with status_area:
                status = BatchStatus(jobs)
        except Exception:
            inputs.unfreeze()
            logger.exception("Batch initialization failed")
            ui.notify("处理未完成，请查看工具日志后重试", type="negative")
            return

        async def handle(path: str) -> str:
            source = Path(path)

            def write(destination: Path) -> None:
                export_csv(source, destination, remove_blank)

            try:
                result_id = await run.io_bound(results.outputs.write, source.stem + "_clean.csv", write)
            except (OSError, UnicodeError, csv.Error, ValueError):
                logger.exception("CSV processing failed")
                raise
            results.refresh()
            return result_id

        try:
            await status.run(handle)
        except Exception:
            logger.exception("Batch execution failed")
            ui.notify("处理未完成，请查看工具日志后重试", type="negative")
        finally:
            start.set_enabled(not jobs.running)
            drop_blank.set_enabled(not jobs.running)
            inputs.set_enabled(not jobs.running)

    start.on_click(submit)


if __name__ in {"__main__", "__mp_main__"}:
    main()
    ui.run(title="CSV 批量清理", port=8080, show=True)
