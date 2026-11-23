"""Compose the synthetic tool previews used inside the illustrated animations.

Every pane here is drawn from fixed arrays. Nothing is captured from a running
app, and no user data, model key or real file is read. The panes exist because
the recordings of the previous UI generation no longer match the current app.

Usage: python3 compose_preview.py <output.png> <demo> <language>
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 710, 560
INK = "#26323a"
MUTED = "#8b979e"
RULE = "#e8edef"
FAINT = "#f0f3f4"
ACCENT = "#284d3d"
BAR = "#cfe0d9"
BAR_ON = "#6ea58c"
CHIP = "#e9efec"
GOOD = "#2f7a58"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Prefer a CJK-capable face so Chinese labels never render as boxes."""
    candidates = (
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


DESIGNS = {
    "ledger": {
        "zh": {
            "title": "个人账本",
            "button": "导出账本",
            "tabs": ("收支明细", "月度趋势"),
            "columns": ("日期", "分类", "说明", "金额"),
            "rows": [
                ("10-02", "餐饮", "工作午餐", "-38.00", False),
                ("10-03", "交通", "地铁充值", "-100.00", False),
                ("10-05", "收入", "项目结款", "+4,200.00", True),
                ("10-08", "日用", "超市采购", "-216.40", False),
                ("10-11", "娱乐", "电影票", "-96.00", False),
            ],
            "panel": "本月预算",
            "panel_note": "已用 62%",
        },
        "en": {
            "title": "Personal ledger",
            "button": "Export",
            "tabs": ("Entries", "Monthly trend"),
            "columns": ("Date", "Category", "Note", "Amount"),
            "rows": [
                ("10-02", "Dining", "Team lunch", "-38.00", False),
                ("10-03", "Transit", "Metro top-up", "-100.00", False),
                ("10-05", "Income", "Project payment", "+4,200.00", True),
                ("10-08", "Household", "Groceries", "-216.40", False),
                ("10-11", "Leisure", "Cinema", "-96.00", False),
            ],
            "panel": "Monthly budget",
            "panel_note": "62% used",
        },
    },
    "excel": {
        "zh": {
            "title": "销售统计",
            "button": "导出 Excel",
            "tabs": ("按地区", "按产品"),
            "columns": ("地区", "订单数", "销售额", "占比"),
            "rows": [
                ("华东", "48", "128,400", "31%", False),
                ("华南", "41", "104,900", "25%", False),
                ("华北", "37", "92,300", "22%", False),
                ("西南", "26", "61,200", "15%", False),
                ("其他", "18", "29,700", "7%", False),
            ],
            "panel": "销售额分布",
            "panel_note": "192 行 · 4 个地区",
        },
        "en": {
            "title": "Sales summary",
            "button": "Export",
            "tabs": ("By region", "By product"),
            "columns": ("Region", "Orders", "Sales", "Share"),
            "rows": [
                ("East", "48", "128,400", "31%", False),
                ("South", "41", "104,900", "25%", False),
                ("North", "37", "92,300", "22%", False),
                ("West", "26", "61,200", "15%", False),
                ("Other", "18", "29,700", "7%", False),
            ],
            "panel": "Sales by region",
            "panel_note": "192 rows · 4 regions",
        },
    },
    "customers": {
        "zh": {
            "title": "客户管理",
            "button": "导出客户",
            "tabs": ("全部客户", "跟进中"),
            "columns": ("客户", "联系人", "阶段", "最近跟进"),
            "rows": [
                ("远山科技", "陈女士", "报价", "今天", True),
                ("衡宇材料", "刘先生", "接洽", "昨天", False),
                ("清和设计", "王女士", "成单", "2 天前", False),
                ("北辰物流", "赵先生", "报价", "3 天前", False),
                ("和风餐饮", "周女士", "接洽", "上周", False),
            ],
            "panel": "销售漏斗",
            "panel_note": "接洽 12 · 报价 7 · 成单 3",
        },
        "en": {
            "title": "Customer workspace",
            "button": "Export",
            "tabs": ("All customers", "In progress"),
            "columns": ("Customer", "Contact", "Stage", "Last touch"),
            "rows": [
                ("Yuanshan Tech", "Ms. Chen", "Quoted", "Today", True),
                ("Hengyu Materials", "Mr. Liu", "Contacted", "Yesterday", False),
                ("Qinghe Design", "Ms. Wang", "Won", "2 days ago", False),
                ("Beichen Logistics", "Mr. Zhao", "Quoted", "3 days ago", False),
                ("Hefeng Catering", "Ms. Zhou", "Contacted", "Last week", False),
            ],
            "panel": "Pipeline",
            "panel_note": "Contacted 12 · Quoted 7 · Won 3",
        },
    },
    "documents": {
        "zh": {
            "title": "PDF 整理",
            "button": "生成 PDF",
            "tabs": ("文件顺序", "页码范围"),
            "columns": ("文件", "页数", "已选", "状态"),
            "rows": [
                ("Project-brief.pdf", "2", "1-2", "待合并", False),
                ("Budget-plan.pdf", "2", "1", "待合并", False),
                ("Meeting-notes.pdf", "2", "2", "待合并", False),
                ("Signature.pdf", "1", "1", "待合并", False),
                ("", "", "", "", False),
            ],
            "panel": "共 7 页",
            "panel_note": "输出为新文件，原文件不改动",
        },
        "en": {
            "title": "PDF workspace",
            "button": "Build PDF",
            "tabs": ("File order", "Page ranges"),
            "columns": ("File", "Pages", "Selected", "State"),
            "rows": [
                ("Project-brief.pdf", "2", "1-2", "Pending", False),
                ("Budget-plan.pdf", "2", "1", "Pending", False),
                ("Meeting-notes.pdf", "2", "2", "Pending", False),
                ("Signature.pdf", "1", "1", "Pending", False),
                ("", "", "", "", False),
            ],
            "panel": "7 pages total",
            "panel_note": "New file only; originals untouched",
        },
    },
    "media": {
        "zh": {
            "title": "音视频处理",
            "button": "批量提取",
            "tabs": ("提取音频", "媒体信息"),
            "columns": ("文件", "时长", "格式", "状态"),
            "rows": [
                ("interview-01.mp4", "12:04", "H.264", "就绪", False),
                ("interview-02.mp4", "08:37", "H.264", "就绪", False),
                ("lecture-clip.mp4", "23:15", "H.264", "就绪", False),
                ("", "", "", "", False),
                ("", "", "", "", False),
            ],
            "panel": "区间 00:30 - 02:15",
            "panel_note": "输出 FLAC · 保留原视频",
        },
        "en": {
            "title": "Media workspace",
            "button": "Extract",
            "tabs": ("Extract audio", "Metadata"),
            "columns": ("File", "Length", "Codec", "State"),
            "rows": [
                ("interview-01.mp4", "12:04", "H.264", "Ready", False),
                ("interview-02.mp4", "08:37", "H.264", "Ready", False),
                ("lecture-clip.mp4", "23:15", "H.264", "Ready", False),
                ("", "", "", "", False),
                ("", "", "", "", False),
            ],
            "panel": "Range 00:30 - 02:15",
            "panel_note": "FLAC output · originals kept",
        },
    },
}

BAR_VALUES = [0.42, 0.58, 0.36, 0.71, 0.54, 0.63, 0.48]


def compose(destination: Path, demo: str = "ledger", language: str = "zh") -> None:
    copy = DESIGNS[demo][language]
    image = Image.new("RGB", (WIDTH, HEIGHT), "#fbfcfc")
    draw = ImageDraw.Draw(image)

    draw.text((20, 18), copy["title"], fill=INK, font=font(20, bold=True))
    label_width = draw.textlength(copy["button"], font=font(12)) + 28
    button = (WIDTH - 20 - label_width, 16, WIDTH - 20, 46)
    draw.rounded_rectangle(button, radius=8, fill=ACCENT)
    draw.text((button[0] + 14, button[1] + 9), copy["button"], fill="#ffffff", font=font(12))

    tab_x = 20
    for index, tab in enumerate(copy["tabs"]):
        width = draw.textlength(tab, font=font(12)) + 20
        if index == 0:
            draw.rounded_rectangle((tab_x, 62, tab_x + width, 88), radius=7, fill=CHIP)
            draw.text((tab_x + 10, 68), tab, fill="#2c5747", font=font(12))
        else:
            draw.text((tab_x + 10, 68), tab, fill="#61707a", font=font(12))
        tab_x += width + 8

    columns = copy["columns"]
    column_x = (20, 150, 300, WIDTH - 20)
    top = 116
    for index, column in enumerate(columns):
        anchor = "ra" if index == len(columns) - 1 else "la"
        draw.text((column_x[index], top), column, fill=MUTED, font=font(12), anchor=anchor)
    draw.line((20, top + 24, WIDTH - 20, top + 24), fill=RULE, width=1)

    row_top = top + 24
    for offset, row in enumerate(copy["rows"]):
        date, category, note, amount, positive = row
        if not date:
            break
        y = row_top + 10 + offset * 33
        draw.text((column_x[0], y), date, fill=INK, font=font(12))
        draw.text((column_x[1], y), category, fill=INK, font=font(12))
        draw.text((column_x[2], y), note, fill=INK, font=font(12))
        draw.text(
            (column_x[3], y),
            amount,
            fill=GOOD if positive else INK,
            font=font(12, bold=positive),
            anchor="ra",
        )
        draw.line((20, y + 24, WIDTH - 20, y + 24), fill=FAINT, width=1)

    card = (20, 330, WIDTH - 20, 470)
    draw.rounded_rectangle(card, radius=10, outline=RULE, width=1)
    draw.text((34, 346), copy["panel"], fill="#7c8a92", font=font(12))
    draw.text((WIDTH - 34, 346), copy["panel_note"], fill="#7c8a92", font=font(12), anchor="ra")

    if demo == "documents":
        # A page strip reads more honestly than a bar chart for a PDF assembly.
        pages = 7
        gap = 6
        cell = (WIDTH - 68 - (pages - 1) * gap) / pages
        for index in range(pages):
            left = 34 + index * (cell + gap)
            shade = BAR_ON if index in (0, 1, 3) else BAR
            draw.rounded_rectangle((left, 372, left + cell, 452), radius=3, fill=shade)
    elif demo == "media":
        # A waveform stands in for an audio interval selection.
        heights = [14, 26, 18, 34, 22, 40, 30, 46, 24, 36, 16, 28, 20, 32, 12]
        gap = 5
        cell = (WIDTH - 68 - (len(heights) - 1) * gap) / len(heights)
        for index, height in enumerate(heights):
            left = 34 + index * (cell + gap)
            shade = BAR_ON if 4 <= index <= 9 else BAR
            draw.rounded_rectangle((left, 452 - height * 1.8, left + cell, 452), radius=2, fill=shade)
    else:
        slot = (WIDTH - 68 - 34 - 6 * 9) / len(BAR_VALUES)
        highlight = 3 if demo == "ledger" else 0
        for index, value in enumerate(BAR_VALUES):
            left = 34 + index * (slot + 9)
            height = int(value * 74)
            draw.rounded_rectangle(
                (left, 452 - height, left + slot, 452),
                radius=3,
                fill=BAR_ON if index == highlight else BAR,
            )
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)
    print(f"preview: {demo}-{language} -> {destination}")


if __name__ == "__main__":
    target = Path(sys.argv[1])
    demo = sys.argv[2] if len(sys.argv) > 2 else "ledger"
    language = sys.argv[3] if len(sys.argv) > 3 else "zh"
    compose(target, demo, language)
