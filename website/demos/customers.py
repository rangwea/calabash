"""
project: showcase
name: Customer workspace
description: Local SQLite customer records, editable follow-ups, stage filters and export.
creator: Calabash showcase
created_at: 2026-10-26
updated_at: 2026-10-26
tags: crm,sqlite,customers
"""

import csv
import sqlite3

from nicegui import run, ui

from component.tool_results import ToolResults
from core.local_paths import app_dir


def main():
    english = getattr(ui.context.client, "demo_language", "zh") == "en"
    tr = lambda zh, en: en if english else zh
    directory = app_dir() / "showcase"
    directory.mkdir(parents=True, exist_ok=True)
    database = directory / ("customers-en.db" if english else "customers-zh.db")
    stages = {
        "all": tr("全部客户", "All customers"),
        "lead": tr("待联系", "New lead"),
        "active": tr("洽谈中", "In progress"),
        "won": tr("已合作", "Active client"),
    }
    names = [
        ("澄光设计", "Lucent Design"),
        ("行远科技", "Waypoint Labs"),
        ("青禾咖啡", "Meadow Coffee"),
        ("拾光工作室", "Daylight Studio"),
        ("森序家居", "Grove Living"),
        ("方舟教育", "Harbor Learning"),
        ("见山品牌", "Summit Brand"),
        ("云帆咨询", "Cloudsail Consulting"),
    ]
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY,zh TEXT,en TEXT,contact TEXT,email TEXT,stage TEXT,value INTEGER,note TEXT)"
        )
        if not db.execute("SELECT COUNT(*) FROM customers").fetchone()[0]:
            db.executemany(
                "INSERT INTO customers VALUES(?,?,?,?,?,?,?,?)",
                [
                    (
                        i + 1,
                        *names[i],
                        f"Demo contact {i + 1}",
                        f"contact{i + 1}@customer.example",
                        ["active", "lead", "won", "active"][i % 4],
                        [48000, 32000, 86000, 64000][i % 4],
                        tr(
                            "已发送方案，等待反馈", "Proposal shared; awaiting feedback"
                        ),
                    )
                    for i in range(len(names))
                ],
            )
    state = {"stage": "all", "selected": 1, "search": ""}

    def records():
        with sqlite3.connect(database) as db:
            db.row_factory = sqlite3.Row
            return [
                dict(row) for row in db.execute("SELECT * FROM customers ORDER BY id")
            ]

    def choose(event):
        if event.selection:
            state["selected"] = event.selection[0]["id"]
            detail.refresh()

    def refresh_search(event):
        state["search"] = (event.value or "").lower()
        listing.refresh()

    async def export():
        snapshot = records()
        results.start_run()

        def write(path):
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ["Company", "Contact", "Email", "Stage", "Value", "Follow-up"]
                )
                writer.writerows(
                    (
                        r["en" if english else "zh"],
                        r["contact"],
                        r["email"],
                        r["stage"],
                        r["value"],
                        r["note"],
                    )
                    for r in snapshot
                )

        await run.io_bound(results.outputs.write, "customer-pipeline.csv", write)
        results.refresh()
        results.container.set_visibility(True)

    with ui.column().classes("w-full gap-4"):
        with ui.row().classes("w-full justify-between items-center gap-3 flex-nowrap"):
            with ui.column().classes("gap-1"):
                ui.label(
                    tr("每一次跟进，都有下一步。", "Every relationship, a next step.")
                ).classes("text-lg font-semibold")
                ui.label(
                    tr(
                        "客户资料、销售阶段与跟进记录",
                        "Contacts, pipeline stages and follow-ups",
                    )
                ).classes("text-xs text-gray-500")
            ui.button(
                tr("导出客户", "Export customers"),
                icon="o_file_download",
                on_click=export,
            ).props("flat dense color=grey-7").props("data-testid=customers-export")

        @ui.refreshable
        def summary():
            rows = records()
            with ui.row().classes(
                "w-full border-y border-gray-200 py-4 gap-0 flex-nowrap"
            ):
                for label, value in [
                    (tr("客户总数", "Total customers"), str(len(rows))),
                    (
                        tr("洽谈中", "In progress"),
                        str(sum(r["stage"] == "active" for r in rows)),
                    ),
                    (
                        tr("合作金额", "Pipeline value"),
                        f"¥ {sum(r['value'] for r in rows):,}",
                    ),
                ]:
                    with ui.column().classes("flex-1 gap-1"):
                        ui.label(label).classes("text-xs text-gray-500")
                        ui.label(value).classes("text-2xl font-semibold text-gray-900")

        summary()
        with ui.row().classes("w-full items-center justify-between gap-3 flex-nowrap"):
            ui.input(
                placeholder=tr("搜索客户或联系人", "Search customers or contacts"),
                on_change=refresh_search,
            ).props("outlined dense hide-bottom-space clearable").classes("w-64").props(
                "data-testid=customers-search"
            )
            ui.toggle(
                stages,
                value="all",
                on_change=lambda event: (
                    state.update(stage=event.value),
                    listing.refresh(),
                ),
            ).props(
                "dense no-caps unelevated color=grey-2 text-color=grey-7 toggle-color=primary"
            ).props("data-testid=customers-filter")
        with ui.grid(columns=12).classes("w-full gap-5"):
            with ui.column().classes("col-span-8 min-w-0 gap-2"):

                @ui.refreshable
                def listing():
                    filtered = [
                        r
                        for r in records()
                        if (state["stage"] == "all" or r["stage"] == state["stage"])
                        and (
                            not state["search"]
                            or state["search"]
                            in (r["zh"] + r["en"] + r["contact"]).lower()
                        )
                    ]
                    rows = [
                        {
                            **r,
                            "company": r["en" if english else "zh"],
                            "stage_label": stages[r["stage"]],
                            "amount": f"¥ {r['value']:,}",
                        }
                        for r in filtered
                    ]
                    columns = [
                        {
                            "name": key,
                            "label": label,
                            "field": key,
                            "align": "left",
                            "sortable": True,
                        }
                        for key, label in [
                            ("company", tr("客户名称", "Company")),
                            ("contact", tr("联系人", "Contact")),
                            ("stage_label", tr("阶段", "Stage")),
                            ("amount", tr("预计金额", "Value")),
                        ]
                    ]
                    table = (
                        ui.table(
                            columns=columns,
                            rows=rows,
                            row_key="id",
                            selection="single",
                            pagination=6,
                            on_select=choose,
                        )
                        .props("flat dense")
                        .classes("w-full demo-table")
                    )
                    table.selected = [r for r in rows if r["id"] == state["selected"]]
                    table.add_slot(
                        "body-cell-stage_label",
                        "<q-td :props=\"props\"><q-badge :color=\"props.row.stage === 'won' ? 'green-1' : props.row.stage === 'active' ? 'blue-1' : 'grey-2'\" :text-color=\"props.row.stage === 'won' ? 'green-9' : props.row.stage === 'active' ? 'blue-9' : 'grey-7'\">{{ props.value }}</q-badge></q-td>",
                    )

                listing()
            with ui.column().classes(
                "col-span-4 min-w-0 border-l border-gray-200 pl-5 gap-3"
            ):

                @ui.refreshable
                def detail():
                    record = next(r for r in records() if r["id"] == state["selected"])
                    with ui.row().classes("gap-3 items-center"):
                        ui.avatar(
                            record["en"][0],
                            color="blue-1",
                            text_color="blue-8",
                            size="38px",
                        )
                        with ui.column().classes("gap-0"):
                            ui.label(record["en" if english else "zh"]).classes(
                                "text-sm font-semibold"
                            )
                            ui.label(record["email"]).classes("text-xs text-gray-500")
                    ui.label(tr("客户资料", "Customer details")).classes(
                        "text-xs font-semibold text-gray-700 mt-2"
                    )
                    contact = (
                        ui.input(tr("联系人", "Contact"), value=record["contact"])
                        .props("outlined dense hide-bottom-space")
                        .classes("w-full")
                    )
                    stage = (
                        ui.select(
                            {k: v for k, v in stages.items() if k != "all"},
                            value=record["stage"],
                            label=tr("销售阶段", "Pipeline stage"),
                        )
                        .props("outlined dense hide-bottom-space")
                        .classes("w-full")
                        .props("data-testid=customers-stage")
                    )
                    note = (
                        ui.textarea(
                            tr("跟进记录", "Follow-up note"), value=record["note"]
                        )
                        .props("outlined dense hide-bottom-space rows=3")
                        .classes("w-full")
                        .props("data-testid=customers-note")
                    )

                    def save():
                        if not (contact.value or "").strip():
                            ui.notify(
                                tr("联系人不能为空", "Contact is required"),
                                type="warning",
                            )
                            return
                        with sqlite3.connect(database) as db:
                            db.execute(
                                "UPDATE customers SET contact=?,stage=?,note=? WHERE id=?",
                                (
                                    contact.value.strip(),
                                    stage.value,
                                    note.value,
                                    record["id"],
                                ),
                            )
                        listing.refresh()
                        summary.refresh()
                        ui.notify(
                            tr("客户资料已更新", "Customer updated"), type="positive"
                        )

                    ui.button(
                        tr("保存更改", "Save changes"), icon="check", on_click=save
                    ).props("dense unelevated color=primary").classes("w-full").props(
                        "data-testid=customers-save"
                    )

                detail()
        results = ToolResults()
        results.container.set_visibility(False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
    ui.run(title="Calabash showcase", reload=False, show=False)
