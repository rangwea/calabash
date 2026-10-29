"""Shared desktop runtime contract and explicit, offline packaging smoke test."""

import json
import tempfile
from importlib import import_module
from pathlib import Path

from core.app_info import APP_NAME, APP_VERSION

CATALOG = Path(__file__).resolve().parents[1] / "agent/skills/calabash/references/runtime-libraries.json"


def catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def agent_guidance() -> str:
    data = catalog()
    libraries = "；".join(f"{item['module']}：{item['purpose']}" for item in data["libraries"])
    from service.capabilities.media_runtime import MediaRuntime
    media = MediaRuntime().status()
    media_guidance = (
        "media.ffmpeg 已安装并校验通过，版本 " + str(media["version"])
        if media["state"] == "ready"
        else "media.ffmpeg 当前不可用或未安装；用户可在设置中导入可信的本地插件 ZIP"
    )
    return (
        "桌面工具运行于应用内置 Python，不依赖用户系统 Python、pip、uv 或终端程序。优先使用标准库和以下随包工具库："
        + libraries
        + "。常用标准库：" + ", ".join(data["stdlib"])
        + "。未内置：" + "、".join(data["not_bundled"])
        + "。可选媒体能力状态：" + media_guidance
        + "。安装后仅通过 service.capabilities.media_runtime.MediaRuntime 的 probe/convert/extract_audio 处理用户选择的本地文件；"
        "使用可选能力必须在工具模块 docstring 声明 requires: media.ffmpeg>=9.0.2（最低版本按实际需要选择）；"
        "多个能力用英文逗号分隔，不需要可选能力时省略或留空。宿主在导入模块前检查能力，缺失时用户导入 ZIP 后手动重试，"
        "不自动执行任务，不把 Python 包名或 URL 写进 requires，不通过 pip/brew 安装。"
        "阻塞调用使用 await run.io_bound，取消使用 threading.Event，不拼装命令行或调用系统 ffmpeg。"
        "document.ocr 尚未实现；不把 FFmpeg 当作语音转写或视频理解模型"
        + "。不要将开发环境已安装或系统 PATH 中的包/程序当成内置能力，不运行 pip/uv/brew/npm 等安装命令，"
        "不要求用户安装系统工具。需要未提供的能力时如实说明限制和已有能力的替代方案，不编造已完成。"
        "图表优先 ui.echart；XLSX 使用 openpyxl 或 pandas 的 openpyxl engine；旧版 xls/doc、扫描 PDF 和音视频理解不能冒充已支持。"
        "Python 工具与宿主共享系统权限，不是沙箱；库可用不等于已取得网络、文件或破坏性操作授权。"
    )


def check_runtime() -> dict:
    """Exercise actual imports and office writers without network or system tools."""
    data = catalog()
    versions, errors, checks = {}, {}, []
    for item in data["libraries"]:
        name = item["module"]
        try:
            module = import_module(name)
            versions[name] = str(getattr(module, "__version__", "bundled"))
        except Exception as error:  # noqa: BLE001 - report arbitrary native library initialization failures.
            errors[name] = type(error).__name__
    for name in data["hidden_imports"] + data["stdlib"]:
        try:
            import_module(name)
        except Exception as error:  # noqa: BLE001 - the selfcheck must produce a failed result, not crash midway.
            errors[name] = type(error).__name__
    if not errors:
        try:
            import numpy as np
            import pandas as pd
            from docx import Document
            from pypdf import PdfReader, PdfWriter

            with tempfile.TemporaryDirectory(prefix="calabash-runtime-") as directory:
                root = Path(directory)
                frame = pd.DataFrame({"team": ["A", "A", "B"], "amount": [10, 5, 20]})
                frame.to_excel(root / "test.xlsx", index=False, engine="openpyxl")
                restored = pd.read_excel(root / "test.xlsx", engine="openpyxl")
                if restored.groupby("team")["amount"].sum().to_dict() != {"A": 15, "B": 20} or np.sum([1, 2]) != 3:
                    raise ValueError("spreadsheet roundtrip")
                document = Document()
                document.add_paragraph("Synthetic runtime check")
                document.save(root / "test.docx")
                if Document(root / "test.docx").paragraphs[0].text != "Synthetic runtime check":
                    raise ValueError("docx roundtrip")
                writer = PdfWriter()
                writer.add_blank_page(width=100, height=100)
                writer.write(root / "test.pdf")
                with (root / "test.pdf").open("rb") as handle:
                    if len(PdfReader(handle).pages) != 1:
                        raise ValueError("pdf roundtrip")
                checks.append("office_roundtrip")
                import pypdfium2 as pdfium
                from PIL import Image
                from reportlab.pdfgen import canvas

                with Image.new("RGB", (64, 32), "red") as image:
                    image.save(root / "image.jpg", quality=90)
                with Image.open(root / "image.jpg") as image:
                    image.resize((32, 16)).save(root / "image.png")
                with Image.open(root / "image.png") as image:
                    if image.size != (32, 16) or image.getpixel((8, 8))[0] < 200:
                        raise ValueError("image roundtrip")
                checks.append("image_roundtrip")
                pdf = canvas.Canvas(str(root / "generated.pdf"), pagesize=(128, 128))
                pdf.drawString(5, 100, "Runtime check")
                pdf.drawImage(str(root / "image.png"), 10, 10, width=64, height=32)
                pdf.save()
                with (root / "generated.pdf").open("rb") as handle:
                    if "Runtime check" not in PdfReader(handle).pages[0].extract_text():
                        raise ValueError("pdf generation")
                checks.append("pdf_generation")
                document = pdfium.PdfDocument(root / "generated.pdf")
                try:
                    page = document[0]
                    try:
                        bitmap = page.render(scale=1)
                        try:
                            rendered = bitmap.to_pil()
                            try:
                                if rendered.size != (128, 128) or all(low >= 200 for low, _ in rendered.convert("RGB").getextrema()):
                                    raise ValueError("pdf rendering")
                            finally:
                                rendered.close()
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
                finally:
                    document.close()
                checks.append("pdf_rendering")
                from service.chat.agent_selfcheck import check_runtime as check_agent
                check_agent()
                checks.append("agent_checkpoint_roundtrip")
        except Exception as error:  # noqa: BLE001 - third-party codecs and renderers have different error types.
            errors["file_roundtrip"] = type(error).__name__
    return {"ok": not errors, "app": {"name": APP_NAME, "version": APP_VERSION}, "libraries": versions, "checks": checks, "errors": errors}
