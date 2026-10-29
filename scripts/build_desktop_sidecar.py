"""Build the Calabash Python backend as a Tauri sidecar binary."""

from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAURI_DIR = ROOT / "src-tauri"
BIN_DIR = TAURI_DIR / "binaries"
PYINSTALLER_WORK_DIR = ROOT / "build" / "pyinstaller"
BACKEND_ENTRY = ROOT / "backend" / "desktop_server.py"
SIDECAR_NAME = "calabash-backend"


def _host_triple() -> str:
    try:
        result = subprocess.run(
            ["rustc", "-vV"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("host: "):
                return line.removeprefix("host: ").strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    machine = platform.machine().lower()
    system = platform.system().lower()
    if system == "darwin":
        return "aarch64-apple-darwin" if machine in {"arm64", "aarch64"} else "x86_64-apple-darwin"
    if system == "linux":
        return "aarch64-unknown-linux-gnu" if machine in {"arm64", "aarch64"} else "x86_64-unknown-linux-gnu"
    if system == "windows":
        return "x86_64-pc-windows-msvc"
    raise RuntimeError(f"Unsupported platform for sidecar build: {system} {machine}")


def _run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    target_triple = _host_triple()
    exe_suffix = ".exe" if os.name == "nt" else ""
    base_binary = BIN_DIR / f"{SIDECAR_NAME}{exe_suffix}"
    sidecar_binary = BIN_DIR / f"{SIDECAR_NAME}-{target_triple}{exe_suffix}"

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    PYINSTALLER_WORK_DIR.mkdir(parents=True, exist_ok=True)

    command = [
        "uv",
        "run",
        "--group",
        "desktop",
        "pyinstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        SIDECAR_NAME,
        "--distpath",
        str(BIN_DIR),
        "--workpath",
        str(PYINSTALLER_WORK_DIR),
        "--specpath",
        str(PYINSTALLER_WORK_DIR),
        "--paths",
        str(ROOT),
        "--add-data",
        f"{ROOT / 'package.json'}{os.pathsep}.",
        "--add-data",
        f"{ROOT / 'core' / 'locales'}{os.pathsep}core/locales",
        "--add-data",
        f"{ROOT / 'component' / 'native_file_drop.js'}{os.pathsep}component",
        "--add-data",
        f"{ROOT / 'component' / 'tool_activity.js'}{os.pathsep}component",
        "--add-data",
        f"{ROOT / 'component' / 'context_menu.js'}{os.pathsep}component",
        "--add-data",
        f"{ROOT / 'component' / 'assets' / 'calabash.png'}{os.pathsep}component/assets",
        "--add-data",
        f"{ROOT / 'component' / 'assets' / 'fluent_tokens.css'}{os.pathsep}component/assets",
        "--add-data",
        f"{ROOT / 'agent' / 'skills' / 'calabash'}{os.pathsep}agent/skills/calabash",
        "--collect-all",
        "nicegui",
        "--collect-all",
        "fastapi",
        "--collect-all",
        "uvicorn",
        "--collect-all",
        "starlette",
        "--hidden-import",
        "backend.desktop_server",
        "--hidden-import",
        "service.files.file_reader_worker",
        "--hidden-import",
        "component.tool_files",
        "--hidden-import",
        "component.tool_results",
        "--hidden-import",
        "service.tools.tool_jobs",
        "--hidden-import",
        "ui.pages",
        "--hidden-import",
        "ui.pages.home",
        "--hidden-import",
        "ui.pages.tools",
        "--hidden-import",
        "api.health_api",
        "--hidden-import",
        "ui.pages.preview",
        str(BACKEND_ENTRY),
    ]
    catalog_path = ROOT / "agent/skills/calabash/references/runtime-libraries.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    imports = [item["module"] for item in catalog["libraries"]] + catalog["hidden_imports"] + catalog["stdlib"]
    for module in imports:
        command[-1:-1] = ["--hidden-import", module]
    for item in catalog["libraries"]:
        for module in item.get("collect_all", []):
            command[-1:-1] = ["--collect-all", module]
    # Agent profiles are discovered dynamically and Pydantic/LangChain inspect
    # distribution metadata at runtime. Keep these out of the user-tool library
    # catalog: they implement the assistant, not generated tool dependencies.
    for module in ("deepagents", "langchain", "langchain_core", "langgraph", "langsmith", "langchain_anthropic"):
        command[-1:-1] = ["--collect-all", module]
    for distribution in ("deepagents", "langchain", "langchain-core", "langgraph", "langgraph-checkpoint", "langgraph-prebuilt", "langgraph-checkpoint-sqlite", "langsmith"):
        command[-1:-1] = ["--copy-metadata", distribution]
    command[-1:-1] = ["--hidden-import", "service.chat.agent_selfcheck", "--hidden-import", "langgraph.checkpoint.sqlite.aio"]
    _run(command)

    if not base_binary.exists():
        raise FileNotFoundError(f"PyInstaller did not create {base_binary}")

    if sidecar_binary.exists():
        sidecar_binary.unlink()
    shutil.move(str(base_binary), str(sidecar_binary))

    mode = sidecar_binary.stat().st_mode
    sidecar_binary.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    _run([str(sidecar_binary), "--check-runtime"])
    print(f"Built desktop sidecar: {sidecar_binary}")


if __name__ == "__main__":
    main()
