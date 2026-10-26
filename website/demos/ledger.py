"""
project: showcase
name: Monthly ledger
description: Synthetic-data ledger with real SQLite entries, budget tracking and CSV export.
creator: Calabash showcase
created_at: 2026-10-26
updated_at: 2026-10-26
tags: finance,sqlite,charts
"""

import csv
import sqlite3

from nicegui import run, ui

from component.tool_results import ToolResults
from core.local_paths import app_dir


def main():
    english = getattr(ui.context.client, "demo_language", "zh") == "en"
    tr = lambda zh, en: en if english else zh
    root = app_dir() / "showcase"
    root.mkdir(parents=True, exist_ok=True)
    database = root / ("ledger-en.db" if english else "ledger-zh.db")
    categories = {
        "all": tr("全部分类", "All categories"),
        "income": tr("收入", "Income"),
        "food": tr("餐饮", "Food"),
        "shopping": tr("购物", "Shopping"),
        "travel": tr("交通", "Travel"),
        "home": tr("居家", "Home"),
    }
    seed = [
        ("10-01", "income", "项目收入 / Project payment", 18600),
        ("10-02", "home", "房租 / Rent", -4200),
        ("10-04", "food", "周末聚餐 / Dinner", -268),
        ("10-06", "shopping", "键盘 / Keyboard", -699),
        ("10-09", "food", "咖啡与午餐 / Coffee & lunch", -86),
        ("10-12", "travel", "通勤 / Commute", -168),
        ("10-15", "income", "设计收入 / Design payment", 5200),
        ("10-18", "food", "超市采购 / Groceries", -326),
        ("10-21", "shopping", "办公用品 / Office supplies", -249),
        ("10-23", "travel", "城际交通 / Train tickets", -385),
    ]
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS entries (id INTEGER PRIMARY KEY, day TEXT, category TEXT, note TEXT, amount REAL)"
        )
        if not db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]:
            db.executemany(
                "INSERT INTO entries(day,category,note,amount) VALUES(?,?,?,?)", seed
            )
    state = {"category": "all"}

    def entries():
        with sqlite3.connect(database) as db:
            return db.execute(
                "SELECT id,day,category,note,amount FROM entries ORDER BY day DESC,id DESC"
            ).fetchall()

    def add_entry():
        with ui.dialog() as dialog, ui.card().classes("w-96 max-w-full gap-4"):
            ui.label(tr("记一笔", "New transaction")).classes("text-base font-semibold")
            note = (
                ui.input(tr("用途", "Description"), value="")
                .props("outlined dense hide-bottom-space")
                .classes("w-full")
                .props("data-testid=ledger-note")
            )
            amount = (
                ui.number(
                    tr("支出金额", "Expense amount"), value=128, min=0.01, precision=2
                )
                .props("outlined dense hide-bottom-space prefix=¥")
                .classes("w-full")
                .props("data-testid=ledger-amount")
            )
            category = (
                ui.select(
                    {
                        key: value
                        for key, value in categories.items()
                        if key not in {"all", "income"}
                    },
                    value="food",
                    label=tr("分类", "Category"),
                )
                .props("outlined dense hide-bottom-space")
                .classes("w-full")
            )

            def save():
                if not note.value or not amount.value or amount.value <= 0:
                    ui.notify(
                        tr(
                            "请填写用途和正数金额",
                            "Enter a description and a positive amount",
                        ),
                        type="warning",
                    )
                    return
                with sqlite3.connect(database) as db:
                    db.execute(
                        "INSERT INTO entries(day,category,note,amount) VALUES(?,?,?,?)",
                        (
                            "10-26",
                            category.value,
                            note.value.strip(),
                            -float(amount.value),
                        ),
                    )
                dialog.close()
                dashboard.refresh()
                ui.notify(
                    tr("已保存到本地账本", "Saved to your local ledger"),
                    type="positive",
                )

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(tr("取消", "Cancel"), on_click=dialog.close).props(
                    "flat dense"
                )
                ui.button(tr("保存记录", "Save transaction"), on_click=save).props(
                    "dense unelevated color=primary"
                ).props("data-testid=ledger-save")
        dialog.open()

    async def export():
        snapshot = entries()
        results.start_run()

        def write(path):
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Date", "Category", "Description", "Amount"])
                writer.writerows(
                    (day, category, note, amount)
                    for _, day, category, note, amount in snapshot
                )

        await run.io_bound(results.outputs.write, "monthly-ledger.csv", write)
        results.refresh()
        results.container.set_visibility(True)

    with ui.column().classes("w-full gap-4"):
        with ui.row().classes("w-full items-center justify-between gap-3 flex-nowrap"):
            with ui.column().classes("gap-1"):
                ui.label(
                    tr("把每一笔，记清楚。", "A clear view of every transaction.")
                ).classes("text-lg font-semibold text-gray-900")
                ui.label(
                    tr("2026 年 10 月 · 个人账本", "October 2026 · Personal ledger")
                ).classes("text-xs text-gray-500")
            with ui.row().classes("gap-2 shrink-0 items-center"):
                ui.button(icon="o_file_download", on_click=export).props(
                    "flat dense round color=grey-7"
                ).tooltip(tr("导出账本", "Export ledger")).props(
                    "data-testid=ledger-export"
                )
                ui.button(
                    tr("记一笔", "Add transaction"), icon="add", on_click=add_entry
                ).props("dense unelevated color=primary").props(
                    "data-testid=ledger-add"
                )

        @ui.refreshable
        def dashboard():
            rows = entries()
            income = sum(row[4] for row in rows if row[4] > 0)
            expense = -sum(row[4] for row in rows if row[4] < 0)
            with ui.row().classes(
                "w-full gap-0 border-y border-gray-200 py-4 flex-nowrap"
            ):
                for label, value, color in [
                    (tr("本月结余", "Net balance"), income - expense, "text-gray-900"),
                    (tr("总收入", "Income"), income, "text-emerald-700"),
                    (tr("总支出", "Expenses"), expense, "text-gray-900"),
                ]:
                    with ui.column().classes("flex-1 gap-1"):
                        ui.label(label).classes("text-xs text-gray-500")
                        ui.label(f"¥ {value:,.2f}").classes(
                            f"text-2xl font-semibold {color}"
                        )
            with ui.grid(columns=12).classes("w-full gap-6"):
                with ui.column().classes("col-span-8 min-w-0 gap-2"):
                    ui.label(tr("收支趋势", "Cash flow")).classes(
                        "text-sm font-semibold"
                    )
                    running, trend = 0, []
                    for row in sorted(rows, key=lambda item: (item[1], item[0])):
                        running += row[4]
                        trend.append(round(running, 2))
                    ui.echart(
                        {
                            "grid": {"left": 52, "right": 10, "top": 20, "bottom": 25},
                            "tooltip": {"trigger": "axis"},
                            "xAxis": {
                                "type": "category",
                                "data": [
                                    r[1]
                                    for r in sorted(
                                        rows, key=lambda item: (item[1], item[0])
                                    )
                                ],
                                "axisLine": {"lineStyle": {"color": "#e2e7ed"}},
                                "axisLabel": {"color": "#8a939f"},
                            },
                            "yAxis": {
                                "type": "value",
                                "splitLine": {"lineStyle": {"color": "#edf0f4"}},
                                "axisLabel": {"color": "#8a939f"},
                            },
                            "series": [
                                {
                                    "type": "line",
                                    "data": trend,
                                    "smooth": True,
                                    "symbol": "none",
                                    "lineStyle": {"color": "#3374d6", "width": 2.5},
                                    "areaStyle": {"color": "#e9f1fc"},
                                }
                            ],
                        }
                    ).classes("w-full h-[185px]")
                with ui.column().classes(
                    "col-span-4 min-w-0 gap-3 border-l border-gray-200 pl-5"
                ):
                    ui.label(tr("分类预算", "Category budgets")).classes(
                        "text-sm font-semibold"
                    )
                    for key, budget in [
                        ("food", 1800),
                        ("shopping", 1800),
                        ("travel", 1200),
                    ]:
                        spent = -sum(r[4] for r in rows if r[2] == key and r[4] < 0)
                        with ui.column().classes("w-full gap-1"):
                            with ui.row().classes(
                                "w-full justify-between items-center gap-2"
                            ):
                                ui.label(categories[key]).classes(
                                    "text-xs text-gray-600"
                                )
                                ui.label(f"¥{spent:,.0f} / {budget:,}").classes(
                                    "text-xs text-gray-500"
                                )
                            ui.linear_progress(
                                min(1, spent / budget), show_value=False
                            ).props("color=blue-6 track-color=grey-2 rounded size=5px")
            with ui.row().classes("w-full justify-between items-center gap-2"):
                ui.label(tr("交易明细", "Transactions")).classes(
                    "text-sm font-semibold"
                )
                ui.toggle(
                    {
                        key: categories[key]
                        for key in ["all", "food", "shopping", "travel"]
                    },
                    value=state["category"],
                    on_change=lambda event: (
                        state.update(category=event.value),
                        dashboard.refresh(),
                    ),
                ).props(
                    "dense no-caps unelevated color=grey-2 text-color=grey-7 toggle-color=primary"
                ).props("data-testid=ledger-filter")
            selected = (
                rows
                if state["category"] == "all"
                else [r for r in rows if r[2] == state["category"]]
            )
            data = [
                {
                    "id": row[0],
                    "date": "2026-" + row[1],
                    "category": categories[row[2]],
                    "description": row[3].split(" / ")[-1 if english else 0],
                    "amount": f"{'+' if row[4] > 0 else '-'} ¥ {abs(row[4]):,.2f}",
                }
                for row in selected
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
                    ("date", tr("日期", "Date")),
                    ("description", tr("用途", "Description")),
                    ("category", tr("分类", "Category")),
                    ("amount", tr("金额", "Amount")),
                ]
            ]
            table = (
                ui.table(columns=columns, rows=data, row_key="id", pagination=4)
                .props("flat dense")
                .classes("w-full demo-table")
            )
            table.add_slot(
                "body-cell-amount",
                "<q-td :props=\"props\" :class=\"props.row.amount.startsWith('+') ? 'text-positive' : 'text-grey-8'\">{{ props.value }}</q-td>",
            )

        dashboard()
        results = ToolResults()
        results.container.set_visibility(False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
    ui.run(title="Calabash showcase", reload=False, show=False)
