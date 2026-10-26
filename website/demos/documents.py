"""
project: showcase
name: Document workspace
description: Real PDF thumbnails, reordering, page selection, merging and safe exports.
creator: Calabash showcase
created_at: 2026-10-26
updated_at: 2026-10-26
tags: pdf,files,batch
"""

import base64
import io
from pathlib import Path

import pypdfium2 as pdfium
from nicegui import run, ui
from pypdf import PdfReader, PdfWriter

from component.tool_files import ToolFileInput
from component.tool_results import ToolJobStatus, ToolResults
from service.tools.tool_jobs import ToolJobs, ToolTask


def thumbnail(path):
    with pdfium.PdfDocument(path) as document:
        page = document[0]
        bitmap = page.render(scale=0.3)
        image = bitmap.to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        data = base64.b64encode(buffer.getvalue()).decode()
        bitmap.close()
        page.close()
        return {
            "path": str(path),
            "pages": len(document),
            "image": "data:image/png;base64," + data,
        }


def main():
    english = getattr(ui.context.client, "demo_language", "zh") == "en"
    tr = lambda zh, en: en if english else zh
    state = {"documents": []}
    with ui.column().classes("w-full gap-4"):
        with ui.column().classes("gap-1"):
            ui.label(
                tr("让散落的文件，井然有序。", "Bring your documents into order.")
            ).classes("text-lg font-semibold")
            ui.label(
                tr(
                    "预览页面、调整顺序，再合并或拆分",
                    "Preview pages, reorder, then merge or split",
                )
            ).classes("text-xs text-gray-500")
        with ui.grid(columns=12).classes("w-full gap-6"):
            with ui.column().classes("col-span-5 min-w-0 gap-3"):
                ui.label(tr("输入文件", "Input files")).classes("text-sm font-semibold")
                inputs = ToolFileInput()

                async def preview():
                    if not inputs.paths:
                        return
                    inspect.disable()
                    try:
                        paths = inputs.freeze()
                        if len(paths) > 10 or any(
                            Path(path).suffix.lower() != ".pdf" for path in paths
                        ):
                            raise ValueError("Select up to 10 PDFs")
                        state["documents"] = [
                            await run.io_bound(thumbnail, path) for path in paths
                        ]
                        gallery.refresh()
                    except (OSError, ValueError):
                        ui.notify(
                            tr("无法预览所选 PDF", "Cannot preview selected PDFs"),
                            type="negative",
                        )
                    finally:
                        inputs.unfreeze()
                        inspect.enable()

                inspect = (
                    ui.button(
                        tr("预览页面", "Preview pages"),
                        icon="o_visibility",
                        on_click=preview,
                    )
                    .props("outline dense color=grey-7")
                    .props("data-testid=documents-preview")
                )
            with ui.column().classes(
                "col-span-7 min-w-0 gap-3 border-l border-gray-200 pl-5"
            ):

                @ui.refreshable
                def gallery():
                    docs = state["documents"]
                    with ui.row().classes("w-full justify-between items-center gap-2"):
                        ui.label(tr("输出顺序", "Output order")).classes(
                            "text-sm font-semibold"
                        )
                        ui.label(
                            tr(
                                f"{sum(d['pages'] for d in docs)} 页",
                                f"{sum(d['pages'] for d in docs)} pages",
                            )
                        ).classes("text-xs text-gray-500")
                    if not docs:
                        with ui.column().classes(
                            "w-full h-56 border border-dashed border-gray-300 rounded-md items-center justify-center gap-3"
                        ):
                            ui.icon("picture_as_pdf", size="30px").classes(
                                "text-gray-300"
                            )
                            ui.label(
                                tr(
                                    "文件预览会显示在这里",
                                    "Document previews appear here",
                                )
                            ).classes("text-xs text-gray-400")
                        return
                    with ui.grid(columns=3).classes("w-full gap-3"):
                        for index, doc in enumerate(docs):
                            with ui.column().classes("gap-2 min-w-0"):
                                ui.image(doc["image"]).props(
                                    "fit=contain no-spinner"
                                ).classes(
                                    "w-full h-44 bg-white border border-gray-200 rounded-md"
                                )
                                ui.label(doc["path"].split("/")[-1]).classes(
                                    "w-full text-[11px] text-gray-600 truncate"
                                )
                                with ui.row().classes(
                                    "w-full items-center justify-between gap-0"
                                ):
                                    ui.label(f"{index + 1:02}").classes(
                                        "text-xs font-semibold text-gray-400"
                                    )

                                    def move(i=index):
                                        if i > 0 and not status.jobs.running:
                                            docs[i - 1], docs[i] = docs[i], docs[i - 1]
                                            gallery.refresh()

                                    button = (
                                        ui.button(icon="arrow_back", on_click=move)
                                        .props("flat dense round size=sm")
                                        .tooltip(tr("向前移动", "Move earlier"))
                                        .props(f"data-testid=documents-move-{index}")
                                    )
                                    if index == 0:
                                        button.disable()

                gallery()
        with ui.grid(columns=3).classes(
            "w-full border-t border-gray-200 pt-4 gap-3 items-end"
        ):
            mode = (
                ui.select(
                    {
                        "merge": tr("合并为一个 PDF", "Merge into one PDF"),
                        "split": tr("按原文件分别导出", "Export each PDF separately"),
                    },
                    value="merge",
                    label=tr("输出方式", "Output mode"),
                )
                .props("outlined dense hide-bottom-space")
                .classes("w-full")
            )
            pages = (
                ui.input(
                    tr("每份文件的页码", "Pages in each document"),
                    value="",
                    placeholder=tr("全部，或如 1-2", "All, or e.g. 1-2"),
                )
                .props("outlined dense hide-bottom-space")
                .classes("w-full")
                .props("data-testid=documents-range")
            )

            async def execute():
                if status.jobs.running or not state["documents"]:
                    return
                snapshot = tuple(d["path"] for d in state["documents"])
                if set(snapshot) != set(inputs.paths):
                    ui.notify(
                        tr(
                            "文件列表已变更，请重新预览", "Files changed; preview again"
                        ),
                        type="warning",
                    )
                    return
                selection = (pages.value or "").strip()
                try:
                    indexes = (
                        None
                        if not selection
                        else [int(selection) - 1]
                        if "-" not in selection
                        else list(
                            range(
                                int(selection.split("-")[0]) - 1,
                                int(selection.split("-")[1]),
                            )
                        )
                    )
                    if indexes is not None and (
                        not indexes
                        or min(indexes) < 0
                        or any(max(indexes) >= d["pages"] for d in state["documents"])
                    ):
                        raise ValueError("Invalid pages")
                except (ValueError, IndexError):
                    ui.notify(
                        tr("请输入有效页码范围", "Enter a valid page range"),
                        type="warning",
                    )
                    return
                results.start_run()
                merge = mode.value == "merge"
                status.jobs = (
                    ToolTask(owner=status.jobs.owner)
                    if merge
                    else ToolJobs(snapshot, owner=status.jobs.owner)
                )

                def write(paths, destination):
                    writer = PdfWriter()
                    for path in paths:
                        reader = PdfReader(path)
                        for index in (
                            range(len(reader.pages)) if indexes is None else indexes
                        ):
                            writer.add_page(reader.pages[index])
                    with destination.open("wb") as handle:
                        writer.write(handle)
                    writer.close()

                async def export_one(path):
                    await run.io_bound(
                        results.outputs.write,
                        Path(path).stem + "-selected.pdf",
                        lambda destination: write((path,), destination),
                    )
                    results.refresh()

                async def export_all():
                    await run.io_bound(
                        results.outputs.write,
                        "merged-documents.pdf",
                        lambda destination: write(snapshot, destination),
                    )
                    results.refresh()

                results.container.set_visibility(True)
                await status.run(export_all if merge else export_one)

            start = (
                ui.button(
                    tr("生成 PDF", "Create PDF"),
                    icon="o_file_download",
                    on_click=execute,
                )
                .props("dense unelevated color=primary")
                .classes("h-10")
                .props("data-testid=documents-run")
            )
        status = ToolJobStatus(
            ToolTask(), inputs=(inputs,), controls=(start, mode, pages, inspect)
        )
        results = ToolResults()
        results.container.set_visibility(False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
    ui.run(title="Calabash showcase", reload=False, show=False)
