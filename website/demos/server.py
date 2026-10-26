"""Isolated showcase recorder server. Requires an explicit disposable HOME."""

import argparse
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--plugin", type=Path)
    args = parser.parse_args()
    home = Path.home().resolve()
    if not str(home).startswith(
        ("/private/tmp/", "/tmp/", "/private/var/folders/", "/var/folders/")
    ):
        raise SystemExit("Use a disposable HOME under the system temporary directory")
    from prepare import prepare

    prepare(args.data, args.plugin)
    from nicegui import app, ui
    from core.app_factory import create_app
    from core.database import db_manager
    from core.i18n import set_language
    from component.tool_shell import render_tool_shell
    from service.tools.tool_runtime import load_tool_entrypoint
    import component.tool_files
    import component.file_access

    fixtures = {
        "excel": [args.data / "October-Sales.xlsx"],
        "documents": list(args.data.glob("*.pdf")),
        "media": list(args.data.glob("*.mp4")),
    }

    async def choose_paths():
        return [
            str(path.resolve())
            for path in fixtures.get(getattr(ui.context.client, "demo_name", ""), [])
        ]

    component.tool_files.choose_paths = choose_paths
    component.file_access.choose_paths = choose_paths
    app.add_static_files("/demo-fixtures", str(args.data))
    titles = {
        "ledger": ("个人账本", "Personal ledger"),
        "excel": ("销售数据工作台", "Sales analytics"),
        "customers": ("客户关系工作台", "Customer workspace"),
        "documents": ("文档工作台", "Document workspace"),
        "media": ("音视频工作台", "Media workspace"),
    }

    @ui.page("/demo/{name}")
    async def demo(name: str, lang: str = "zh"):
        if name not in titles:
            ui.label("Unknown showcase")
            return
        set_language("en" if lang == "en" else "zh-CN")
        ui.context.client.demo_language = lang
        ui.context.client.demo_name = name
        ui.context.client.demo_data = args.data
        ui.context.client.calabash_output_owner = (f"tool:showcase/{name}", None)
        ui.add_css("""
          body {background:#fafbfc;color:#24303f;}
          .nicegui-content {padding:0;gap:0;}
          .q-field--outlined .q-field__control {border-radius:6px;}
          .q-table th {font-size:11px;color:#7c8795;background:#f8fafc;font-weight:500;}
          .q-table td {font-size:12px;height:37px;}
          .q-table__bottom {min-height:35px;font-size:11px;}
          .demo-table {border:1px solid #edf0f4;border-radius:6px;}
          .q-btn {letter-spacing:0;}
          .q-btn .q-icon {font-size:17px;}
          .q-field--dense .q-field__label {font-size:12px;}
          .q-field__native {font-size:13px;}
        """)
        title = titles[name][lang == "en"]
        with render_tool_shell(
            title=title,
            subtitle="Showcase / Synthetic data"
            if lang == "en"
            else "工具演示 / 合成数据",
            show_back=False,
        ):
            entry, is_async = load_tool_entrypoint(
                f"showcase_{name}_{lang}", str(Path(__file__).parent / f"{name}.py")
            )
            if is_async:
                await entry()
            else:
                entry()

    db_manager.create_tables()
    application = create_app()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    print(
        "SHOWCASE_READY " + json.dumps({"url": f"http://127.0.0.1:{port}"}), flush=True
    )
    import uvicorn

    uvicorn.run(
        application, host="127.0.0.1", port=port, access_log=False, log_config=None
    )


if __name__ == "__main__":
    main()
