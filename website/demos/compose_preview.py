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
    "video": {
        "zh": {
            "title": "视频剪裁",
            "button": "导出片段",
            "tabs": ("剪裁", "媒体信息"),
            "columns": ("文件", "时长", "编码", "状态"),
            "rows": [
                ("interview-01.mp4", "12:04", "H.264", "已选择", True),
                ("lecture-clip.mp4", "23:15", "H.264", "可选", False),
                ("meeting-raw.mp4", "41:08", "H.264", "可选", False),
                ("", "", "", "", False),
                ("", "", "", "", False),
            ],
            "panel": "起点 00:32 · 终点 00:44",
            "panel_note": "导出为新文件 · 原视频保留",
        },
        "en": {
            "title": "Video trimming",
            "button": "Export clip",
            "tabs": ("Trim", "Metadata"),
            "columns": ("File", "Length", "Codec", "State"),
            "rows": [
                ("interview-01.mp4", "12:04", "H.264", "Selected", True),
                ("lecture-clip.mp4", "23:15", "H.264", "Available", False),
                ("meeting-raw.mp4", "41:08", "H.264", "Available", False),
                ("", "", "", "", False),
                ("", "", "", "", False),
            ],
            "panel": "Start 00:32 · End 00:44",
            "panel_note": "New file · original kept",
        },
    },
    "watermark": {
        "zh": {
            "title": "图片水印",
            "button": "批量导出",
            "tabs": ("水印设置", "输出格式"),
            "columns": ("图片", "尺寸", "格式", "状态"),
            "rows": [
                ("product-01.jpg", "1920×1280", "JPEG", "就绪", True),
                ("product-02.jpg", "1920×1280", "JPEG", "就绪", False),
                ("product-03.jpg", "1600×1600", "JPEG", "就绪", False),
                ("lookbook.png", "2400×1600", "PNG", "就绪", False),
                ("", "", "", "", False),
            ],
            "panel": "文字：仅供内部评审 · 45° · 30%",
            "panel_note": "输出为新图 · 原图不改动",
        },
        "en": {
            "title": "Image watermarks",
            "button": "Export batch",
            "tabs": ("Watermark", "Output format"),
            "columns": ("Image", "Size", "Format", "State"),
            "rows": [
                ("product-01.jpg", "1920×1280", "JPEG", "Ready", True),
                ("product-02.jpg", "1920×1280", "JPEG", "Ready", False),
                ("product-03.jpg", "1600×1600", "JPEG", "Ready", False),
                ("lookbook.png", "2400×1600", "PNG", "Ready", False),
                ("", "", "", "", False),
            ],
            "panel": "Text: Internal review · 45° · 30%",
            "panel_note": "New images · originals untouched",
        },
    },
    "todo": {
        "zh": {
            "title": "AI 待办",
            "button": "添加",
            "tabs": ("全部", "今天"),
            "columns": ("待办", "建议", "截止", "状态"),
            "rows": [
                ("整理本周会议要点", "拆成 3 个具体任务", "今天", "进行中", True),
                ("准备客户演示材料", "先列大纲再补图", "明天", "待开始", False),
                ("归档上月合同", "按客户名排序", "本周", "待开始", False),
                ("更新报价单模板", "沿用上季度格式", "本周", "已完成", False),
                ("", "", "", "", False),
            ],
            "panel": "一句话创建",
            "panel_note": "AI 给出整理建议 · 保存在本机",
        },
        "en": {
            "title": "AI to-do",
            "button": "Add",
            "tabs": ("All", "Today"),
            "columns": ("Task", "Suggestion", "Due", "State"),
            "rows": [
                ("Summarise this week's meetings", "Split into 3 concrete tasks", "Today", "Doing", True),
                ("Prepare the client demo", "Outline first, then visuals", "Tomorrow", "To do", False),
                ("Archive last month's contracts", "Sort by customer name", "This week", "To do", False),
                ("Update the quote template", "Reuse last quarter's format", "This week", "Done", False),
                ("", "", "", "", False),
            ],
            "panel": "Create from one sentence",
            "panel_note": "AI suggests · stored locally",
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

    if demo == "video":
        # A timeline strip with an in/out range marked reads better than a bar chart.
        track = (34, 408, WIDTH - 34, 424)
        draw.rounded_rectangle(track, radius=8, fill=BAR)
        draw.rounded_rectangle((track[0], track[1], track[0] + 120, track[3]), radius=8, fill=BAR_ON)
        draw.rounded_rectangle((track[0] + 196, track[1], track[0] + 268, track[3]), radius=8, fill=BAR_ON)
        for fraction in (0, 0.25, 0.5, 0.75, 1):
            x = track[0] + fraction * (track[2] - track[0])
            draw.line((x, track[3] + 6, x, track[3] + 12), fill=RULE, width=1)
        draw.text((34, 440), "00:00", fill=MUTED, font=font(10))
        draw.text(((WIDTH) / 2, 440), "06:00", fill=MUTED, font=font(10), anchor="ma")
        draw.text((WIDTH - 34, 440), "12:04", fill=MUTED, font=font(10), anchor="ra")
    elif demo == "watermark":
        # Tiled marks stand in for a repeating watermark preview.
        for row in range(3):
            for column in range(6):
                x = 52 + column * 108
                y = 376 + row * 34
                draw.text((x, y), "SAMPLE", fill="#c8d6d0", font=font(11))
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
