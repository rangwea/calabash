"""Create synthetic fixtures in an explicit temporary directory, never user data."""

import math
import subprocess
import wave
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from reportlab.pdfgen import canvas


def prepare(directory: Path, plugin: Path | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Date", "Region", "Product", "Sales", "Units"])
    regions = ["East", "South", "North", "West"]
    products = ["Desk", "Chair", "Lamp", "Shelf"]
    for index in range(192):
        region = regions[index % 4]
        sheet.append(
            [
                f"2026-10-{index % 26 + 1:02}",
                region,
                products[(index // 4) % 4],
                960 + ((index * 173) % 7400),
                2 + index % 16,
            ]
        )
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="215D9C")
        cell.font = Font(color="FFFFFF", bold=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    workbook.save(directory / "October-Sales.xlsx")
    for index, name in enumerate(["Project-brief", "Budget-plan", "Meeting-notes"]):
        pdf = canvas.Canvas(str(directory / f"{name}.pdf"), pagesize=(595, 842))
        for page in range(2):
            pdf.setFillColorRGB(0.14, 0.22, 0.32)
            pdf.setFont("Helvetica-Bold", 22)
            pdf.drawString(52, 756, name.replace("-", " "))
            pdf.setFont("Helvetica", 10)
            pdf.setFillColorRGB(0.45, 0.49, 0.55)
            pdf.drawString(52, 730, "CALABASH / SYNTHETIC DEMO DOCUMENT")
            for line in range(14):
                pdf.setFillColorRGB(0.91, 0.93, 0.95)
                pdf.rect(
                    52, 676 - line * 29, 440 if line % 3 else 320, 9, fill=1, stroke=0
                )
            pdf.setFont("Helvetica", 10)
            pdf.drawString(52, 60, f"Document {index + 1} / Page {page + 1}")
            pdf.showPage()
        pdf.save()
    with wave.open(str(directory / "source.wav"), "wb") as audio:
        import struct

        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    int(
                        9000
                        * math.sin(2 * math.pi * 220 * i / 16000)
                        * (0.55 + 0.45 * math.sin(i / 6000))
                    ),
                )
                for i in range(16000 * 8)
            )
        )
    if plugin:
        from PIL import Image, ImageDraw, ImageFont

        from service.capabilities.capability_packs import official_manager

        manager = official_manager()
        manager.import_zip(str(plugin))
        with manager.acquire("media.ffmpeg") as (package, root):
            executable = root / package.entries["ffmpeg"]
            for index in range(3):
                destination = directory / f"Studio-briefing-{index + 1}.mp4"
                if destination.is_file() and destination.stat().st_size:
                    continue
                destination.unlink(missing_ok=True)
                image = Image.new("RGB", (640, 360), "#eff5f4")
                draw = ImageDraw.Draw(image)
                draw.rectangle((36, 34, 604, 326), fill="white")
                draw.text(
                    (65, 70),
                    "STUDIO / OCTOBER 2026",
                    fill="#738681",
                    font=ImageFont.load_default(size=16),
                )
                draw.text(
                    (65, 110),
                    "Ideas worth keeping.",
                    fill="#243d38",
                    font=ImageFont.load_default(size=36),
                )
                draw.text(
                    (65, 168),
                    f"Project briefing {index + 1:02}  /  Synthetic demo video",
                    fill="#738681",
                    font=ImageFont.load_default(size=16),
                )
                for bar, value in enumerate([0.4, 0.65, 0.52, 0.84, 0.72, 1]):
                    draw.rectangle(
                        (65 + bar * 74, 276 - int(value * 66), 110 + bar * 74, 276),
                        fill=["#98c6bc", "#bad7e4", "#cedbd7"][bar % 3],
                    )
                raw = directory / f"frames-{index}.rgb"
                raw.write_bytes(image.tobytes() * 8)
                subprocess.run(
                    [
                        str(executable),
                        "-nostdin",
                        "-v",
                        "error",
                        "-n",
                        "-f",
                        "rawvideo",
                        "-pixel_format",
                        "rgb24",
                        "-video_size",
                        "640x360",
                        "-framerate",
                        "1",
                        "-i",
                        str(raw),
                        "-i",
                        str(directory / "source.wav"),
                        "-shortest",
                        "-c:v",
                        "mpeg4",
                        "-pix_fmt",
                        "yuv420p",
                        "-q:v",
                        "5",
                        "-c:a",
                        "aac",
                        str(destination),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=40,
                )
                raw.unlink()
                # Recording-only macOS conversion: the minimal plugin deliberately
                # does not ship an H.264 encoder. This is not an App dependency.
                converter = Path("/usr/bin/avconvert")
                if converter.exists():
                    browser_video = directory / f"browser-{index}.mov"
                    subprocess.run(
                        [
                            str(converter),
                            "--source",
                            str(destination),
                            "--preset",
                            "Preset640x480",
                            "--output",
                            str(browser_video),
                            "--replace",
                        ],
                        check=True,
                        capture_output=True,
                        timeout=60,
                    )
                    browser_video.replace(destination)
