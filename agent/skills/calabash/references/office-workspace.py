"""
project: calabash
name: office_workspace_template
description: 办公分析工作区示例：筛选、指标、图表和明细，全部使用合成数据
creator: auto-generator
created_at: 2026-10-29
updated_at: 2026-10-29
tags: 办公, 分析, 工作区
requires:
"""

from nicegui import ui

SAMPLE_ROWS = [
    {
        "id": 1,
        "name": "品牌素材整理",
        "owner": "林晓",
        "team": "设计",
        "status": "进行中",
        "hours": 24,
    },
    {
        "id": 2,
        "name": "季度经营分析",
        "owner": "陈雨",
        "team": "运营",
        "status": "已完成",
        "hours": 32,
    },
    {
        "id": 3,
        "name": "客户回访计划",
        "owner": "周宁",
        "team": "运营",
        "status": "进行中",
        "hours": 18,
    },
    {
        "id": 4,
        "name": "产品介绍更新",
        "owner": "林晓",
        "team": "设计",
        "status": "待开始",
        "hours": 12,
    },
    {
        "id": 5,
        "name": "费用明细核对",
        "owner": "许禾",
        "team": "财务",
        "status": "已完成",
        "hours": 16,
    },
    {
        "id": 6,
        "name": "月度预算复盘",
        "owner": "许禾",
        "team": "财务",
        "status": "进行中",
        "hours": 20,
    },
]


def select_rows(keyword: str = "", team: str = "全部团队") -> list[dict]:
    """Small in-memory demo; real file/database queries belong in a ToolTask."""
    keyword = keyword.strip().casefold()
    return [
        dict(row)
        for row in SAMPLE_ROWS
        if (team == "全部团队" or row["team"] == team)
        and (
            not keyword
            or keyword in " ".join(str(value) for value in row.values()).casefold()
        )
    ]


def main() -> None:
    ui.add_css("""
    .office-demo { --office-blue:#0f6cbd; --office-teal:#0f766e; --office-purple:#6950a1; }
    .office-demo .office-metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; width:100%; }
    .office-demo .office-analysis { display:grid; grid-template-columns:minmax(0,2fr) minmax(220px,1fr); gap:16px; width:100%; }
    .office-demo .metric-number { font-size:30px; line-height:1.3; font-weight:650; font-variant-numeric:tabular-nums; }
    .office-demo .office-filters { display:flex; gap:12px; flex-wrap:wrap; align-items:center; width:100%; }
    .office-demo .office-search { flex:1 1 220px; min-width:0; }
    @media(max-width:700px) { .office-demo .office-analysis { grid-template-columns:minmax(0,1fr); } }
    @media(max-width:440px) { .office-demo .office-metrics { grid-template-columns:minmax(0,1fr); } }
    """)
    with ui.column().classes("office-demo w-full min-w-0 gap-4"):
        with ui.row().classes("w-full items-center justify-between gap-3"):
            with ui.column().classes("gap-1"):
                ui.label("团队工作概览").classes("tool-title")
                ui.label("把进度与投入放在同一个工作区。").classes("tool-muted")
            ui.badge("交互示例 · 合成数据", color="blue-1", text_color="blue-9")
        with ui.element("section").classes("office-metrics"):
            metrics = []
            for title, color, caption in [
                ("项目数量", "blue", "当前筛选范围"),
                ("已完成", "teal", "按项目状态统计"),
                ("预计投入", "purple", "单位：小时"),
            ]:
                with ui.column().classes("tool-panel gap-2"):
                    ui.label(title).classes("tool-muted")
                    metrics.append(
                        ui.label()
                        .classes("metric-number")
                        .style(f"color:var(--office-{color})")
                    )
                    ui.label(caption).classes("text-xs tool-muted")
        with ui.element("section").classes("office-analysis"):
            with ui.column().classes("tool-panel min-w-0 gap-3"):
                ui.label("团队投入分布").classes("tool-subtitle")
                ui.label("预计工时 · 小时").classes("tool-muted text-xs")
                chart = ui.echart(
                    {
                        "tooltip": {"trigger": "axis"},
                        "grid": {"left": 40, "right": 16, "top": 16, "bottom": 28},
                        "xAxis": {"type": "category", "data": ["设计", "运营", "财务"]},
                        "yAxis": {"type": "value", "minInterval": 1},
                        "series": [{"type": "bar", "barMaxWidth": 44, "data": []}],
                    }
                ).classes("w-full h-56")
            with ui.column().classes("tool-panel gap-4"):
                ui.icon("insights", size="24px").classes("tool-text-accent")
                ui.label("进度快照").classes("tool-subtitle")
                progress = ui.linear_progress(
                    value=0, show_value=False, color="primary"
                ).classes("w-full")
                summary = ui.label().classes("tool-muted")
                ui.label("尝试按团队筛选，图表、指标和明细会一起更新。").classes(
                    "tool-muted text-sm"
                )
        with ui.column().classes("tool-panel w-full min-w-0 gap-4"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("项目明细").classes("tool-subtitle")
                count = ui.label().classes("tool-muted text-xs")
            with ui.element("div").classes("office-filters"):
                keyword = (
                    ui.input(
                        placeholder="搜索项目、负责人或状态",
                        on_change=lambda: refresh(),
                    )
                    .props('outlined dense clearable aria-label="搜索项目"')
                    .classes("office-search")
                )
                keyword.add_slot("prepend", '<q-icon name="search" size="18px" />')
                team = (
                    ui.select(
                        ["全部团队", "设计", "运营", "财务"],
                        value="全部团队",
                        on_change=lambda: refresh(),
                    )
                    .props('outlined dense aria-label="团队"')
                    .classes("w-36")
                )
                ui.button("重置", on_click=lambda: reset()).props(
                    "outline color=primary"
                )
            columns = [
                {
                    "name": key,
                    "label": label,
                    "field": key,
                    "align": "left",
                    "sortable": True,
                }
                for key, label in [
                    ("name", "项目"),
                    ("owner", "负责人"),
                    ("team", "团队"),
                    ("status", "状态"),
                    ("hours", "预计工时（小时）"),
                ]
            ]
            table = (
                ui.table(columns=columns, rows=[], row_key="id", pagination=5)
                .props("flat")
                .classes("w-full")
            )
            table.add_slot(
                "body-cell-status",
                """<q-td :props="props"><q-badge :color="props.value === '已完成' ? 'green-1' : props.value === '进行中' ? 'blue-1' : 'grey-2'" :text-color="props.value === '已完成' ? 'green-9' : props.value === '进行中' ? 'blue-9' : 'grey-8'">{{ props.value }}</q-badge></q-td>""",
            )

        def refresh() -> None:
            rows = select_rows(keyword.value or "", team.value)
            completed = sum(row["status"] == "已完成" for row in rows)
            for element, value in zip(
                metrics, (len(rows), completed, sum(row["hours"] for row in rows))
            ):
                element.set_text(str(value))
            table.update_rows(rows)
            table.pagination["page"] = 1
            table.update()
            colors = ["#0f6cbd", "#0f766e", "#6950a1"]
            chart.options["series"][0]["data"] = [
                {
                    "value": sum(row["hours"] for row in rows if row["team"] == name),
                    "itemStyle": {"color": color, "borderRadius": [5, 5, 0, 0]},
                }
                for name, color in zip(["设计", "运营", "财务"], colors)
            ]
            chart.update()
            progress.set_value(completed / len(rows) if rows else 0)
            summary.set_text(
                f"{completed} / {len(rows)} 个项目已完成"
                if rows
                else "没有匹配的项目，试试其他筛选条件。"
            )
            count.set_text(f"{len(rows)} 个项目")

        def reset() -> None:
            keyword.set_value("")
            team.set_value("全部团队")
            refresh()

        refresh()


if __name__ in {"__main__", "__mp_main__"}:
    main()
    ui.run(title="办公工作区示例", port=8080, show=True)
