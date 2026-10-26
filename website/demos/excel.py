"""
project: showcase
name: Sales analytics
description: Read an XLSX workbook, aggregate real rows, chart by dimension and export a workbook.
creator: Calabash showcase
created_at: 2026-10-26
updated_at: 2026-10-26
tags: excel,analytics,charts
"""

from pathlib import Path

import pandas as pd
from nicegui import run, ui

from component.tool_files import ToolFileInput
from component.tool_results import ToolJobStatus, ToolResults
from service.tools.tool_jobs import ToolTask


def main():
    english = getattr(ui.context.client, "demo_language", "zh") == "en"
    tr = lambda zh, en: en if english else zh
    state = {"frame": None, "summary": None, "group": "Region", "metric": "Sales"}
    with ui.column().classes("w-full gap-3"):
        with ui.row().classes("w-full justify-between items-center"):
            with ui.column().classes("gap-1"):
                ui.label(
                    tr(
                        "从一张表，到一个清晰结论。",
                        "From a spreadsheet to a clear answer.",
                    )
                ).classes("text-lg font-semibold")
                ui.label(
                    tr(
                        "按维度汇总、查看图表、导出完整结果",
                        "Group, visualize and export the complete result",
                    )
                ).classes("text-xs text-gray-500")
            ui.label(tr("XLSX 数据工作台", "XLSX workspace")).classes(
                "text-xs text-gray-400"
            )
        with ui.row().classes(
            "w-full border border-gray-200 rounded-md p-3 items-center gap-3 flex-nowrap"
        ):
            with ui.column().classes("flex-1 min-w-0 gap-0"):
                inputs = ToolFileInput()

            async def load():
                if not inputs.paths:
                    ui.notify(
                        tr("请先选择 Excel 文件", "Choose an Excel workbook first"),
                        type="warning",
                    )
                    return
                read.disable()
                try:
                    paths = inputs.freeze()
                    frame = await run.io_bound(
                        pd.read_excel, Path(paths[0]), engine="openpyxl"
                    )
                    state["frame"] = frame
                    sheet.set_options(["Sales"], value="Sales")
                    group.set_options(list(frame.columns), value="Region")
                    metric.set_options(
                        list(frame.select_dtypes(include="number").columns),
                        value="Sales",
                    )
                    view.refresh()
                    ui.notify(
                        tr(
                            f"工作簿已读取：{len(frame)} 行",
                            f"Workbook loaded: {len(frame)} rows",
                        ),
                        type="positive",
                    )
                except (OSError, ValueError):
                    ui.notify(
                        tr("无法读取工作簿，请检查文件", "Cannot read this workbook"),
                        type="negative",
                    )
                finally:
                    inputs.unfreeze()
                    read.enable()

            read = (
                ui.button(
                    tr("读取工作簿", "Read workbook"),
                    icon="o_folder_open",
                    on_click=load,
                )
                .props("dense unelevated color=primary")
                .props("data-testid=excel-load")
            )
        with ui.grid(columns=4).classes("w-full gap-3 items-end"):
            sheet = (
                ui.select(["Sales"], value="Sales", label=tr("工作表", "Worksheet"))
                .props("outlined dense hide-bottom-space")
                .classes("w-full")
            )
            group = (
                ui.select(
                    ["Region", "Product"],
                    value="Region",
                    label=tr("统计维度", "Group by"),
                )
                .props("outlined dense hide-bottom-space")
                .classes("w-full")
                .props("data-testid=excel-group")
            )
            metric = (
                ui.select(
                    ["Sales", "Units"], value="Sales", label=tr("数值列", "Measure")
                )
                .props("outlined dense hide-bottom-space")
                .classes("w-full")
            )

            async def analyze():
                if state["frame"] is None or status.jobs.running:
                    return
                frame = state["frame"].copy()
                dimension, measure = group.value, metric.value
                status.jobs = ToolTask(owner=status.jobs.owner)

                async def work():
                    summary = await run.io_bound(
                        lambda: (
                            frame.groupby(dimension, dropna=False)[measure]
                            .agg(["sum", "count"])
                            .reset_index()
                            .sort_values("sum", ascending=False)
                        )
                    )
                    state.update(summary=summary, group=dimension, metric=measure)
                    view.refresh()

                await status.run(work)

            calculate = (
                ui.button(tr("生成统计", "Analyze"), icon="bar_chart", on_click=analyze)
                .props("dense unelevated color=primary")
                .classes("h-10")
                .props("data-testid=excel-analyze")
            )
        status = ToolJobStatus(
            ToolTask(), inputs=(inputs,), controls=(calculate, group, metric, read)
        )

        @ui.refreshable
        def view():
            frame = state["frame"]
            summary = state["summary"]
            if frame is None:
                with ui.column().classes(
                    "w-full items-center justify-center h-72 gap-3 border-y border-gray-200"
                ):
                    ui.icon("table_chart", size="32px").classes("text-gray-300")
                    ui.label(
                        tr("选择工作簿，开始分析", "Choose a workbook to begin")
                    ).classes("text-sm text-gray-400")
                return
            with ui.row().classes(
                "w-full border-y border-gray-200 py-3 gap-0 flex-nowrap"
            ):
                for label, value in [
                    (tr("原始数据行数", "Source rows"), f"{len(frame):,}"),
                    (tr("销售总额", "Total sales"), f"¥ {frame['Sales'].sum():,.0f}"),
                    (
                        tr("统计分组", "Groups"),
                        str(
                            len(summary)
                            if summary is not None
                            else frame[group.value].nunique()
                        ),
                    ),
                ]:
                    with ui.column().classes("flex-1 gap-1"):
                        ui.label(label).classes("text-xs text-gray-500")
                        ui.label(value).classes("text-xl font-semibold")
            if summary is not None:
                labels = [str(value) for value in summary.iloc[:, 0]]
                with ui.grid(columns=12).classes("w-full gap-5"):
                    with ui.column().classes("col-span-7 min-w-0 gap-1"):
                        ui.label(
                            tr("销售分布", "Sales distribution")
                            + " · "
                            + state["group"]
                        ).classes("text-sm font-semibold")
                        ui.echart(
                            {
                                "grid": {
                                    "left": 65,
                                    "right": 20,
                                    "top": 15,
                                    "bottom": 25,
                                },
                                "tooltip": {"trigger": "axis"},
                                "xAxis": {
                                    "type": "value",
                                    "splitLine": {"lineStyle": {"color": "#eef1f5"}},
                                },
                                "yAxis": {
                                    "type": "category",
                                    "data": labels,
                                    "inverse": True,
                                    "axisLine": {"show": False},
                                    "axisTick": {"show": False},
                                },
                                "series": [
                                    {
                                        "type": "bar",
                                        "data": [
                                            {
                                                "value": float(value),
                                                "itemStyle": {
                                                    "color": [
                                                        "#3374d6",
                                                        "#32a389",
                                                        "#8495b0",
                                                        "#e4aa57",
                                                    ][i % 4],
                                                    "borderRadius": [0, 4, 4, 0],
                                                },
                                            }
                                            for i, value in enumerate(summary["sum"])
                                        ],
                                        "barWidth": 24,
                                    }
                                ],
                            }
                        ).classes("w-full h-[205px]")
                    with ui.column().classes("col-span-5 min-w-0 gap-2"):
                        ui.label(tr("分组汇总", "Grouped result")).classes(
                            "text-sm font-semibold"
                        )
                        rows = [
                            {
                                "name": str(r.iloc[0]),
                                "total": f"{r['sum']:,.0f}",
                                "count": int(r["count"]),
                            }
                            for _, r in summary.iterrows()
                        ]
                        ui.table(
                            columns=[
                                {
                                    "name": key,
                                    "label": label,
                                    "field": key,
                                    "align": "left",
                                }
                                for key, label in [
                                    ("name", state["group"]),
                                    ("total", tr("汇总值", "Total")),
                                    ("count", tr("行数", "Rows")),
                                ]
                            ],
                            rows=rows,
                            row_key="name",
                        ).props("flat dense").classes("w-full demo-table")
            else:
                ui.label(
                    tr(
                        "数据预览 · 全量数据参与统计",
                        "Preview · aggregation uses all rows",
                    )
                ).classes("text-sm font-semibold")
                ui.table(
                    columns=[
                        {"name": c, "label": c, "field": c, "align": "left"}
                        for c in frame.columns
                    ],
                    rows=frame.head(5)
                    .assign(id=lambda x: range(len(x)))
                    .to_dict("records"),
                    row_key="id",
                ).props("flat dense").classes("w-full demo-table")

        view()

        async def export():
            if state["summary"] is None:
                return
            data = state["summary"].copy()
            results.start_run()
            await run.io_bound(
                results.outputs.write,
                "sales-summary.xlsx",
                lambda path: data.to_excel(path, index=False, engine="openpyxl"),
            )
            results.refresh()
            results.container.set_visibility(True)

        ui.button(
            tr("导出统计结果", "Export result"), icon="o_file_download", on_click=export
        ).props("outline dense color=grey-7").props("data-testid=excel-export")
        results = ToolResults()
        results.container.set_visibility(False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
    ui.run(title="Calabash showcase", reload=False, show=False)
