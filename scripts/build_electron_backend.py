"""Build an onedir Python tool runtime; keep compiler resources outside it."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "build/electron-backend"
    command = [
        "uv",
        "run",
        "--frozen",
        "--group",
        "packaging",
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "calabash-backend",
        "--distpath",
        str(output),
        "--workpath",
        str(ROOT / "build/pyinstaller-electron"),
        "--specpath",
        str(ROOT / "build/pyinstaller-electron"),
        "--paths",
        str(ROOT),
    ]
    for path, target in [
        ("package.json", "."),
        ("core/locales", "core/locales"),
        ("agent/skills/calabash", "agent/skills/calabash"),
    ]:
        command += ["--add-data", str(ROOT / path) + os.pathsep + target]
    for package in ["backend", "service", "core"]:
        command += ["--collect-submodules", package]
    data = json.loads(
        (ROOT / "agent/skills/calabash/references/runtime-libraries.json").read_text()
    )
    for package in [
        "fastapi",
        "uvicorn",
        "starlette",
        *[v["module"] for v in data["libraries"]],
    ]:
        command += ["--collect-all", package]
    for package in [*data["hidden_imports"], *data["stdlib"]]:
        command += ["--hidden-import", package]
    command += [str(ROOT / "backend/packaged_entry.py")]
    subprocess.run(command, cwd=ROOT, check=True)
    binary = (
        output
        / "calabash-backend"
        / ("calabash-backend.exe" if os.name == "nt" else "calabash-backend")
    )
    subprocess.run([str(binary), "--check-runtime"], cwd=output, check=True)


if __name__ == "__main__":
    main()
