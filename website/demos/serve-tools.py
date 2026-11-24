"""Serve real tools locally so they can be opened in a browser.

Each tool is loaded through the real shared runtime with its real backend and
published frontend, then kept open until you stop the process. The URLs print
with their session token, which is what grants access.

Privacy: this reads whatever tools exist under the HOME it runs with. Run it
against an isolated HOME (see --home) if the default profile holds real
personal data. Nothing is uploaded anywhere; every origin is 127.0.0.1.

Usage:
    .venv/bin/python3 website/demos/serve-tools.py image_watermark/image_watermark default/video_clip_trimmer
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main(targets: list[str]) -> None:
    import core.logger  # noqa: F401 - must import before any run starts
    from service.tools.tool_workers import ToolWorkers

    runtime = ToolWorkers()
    opened = []
    for target in targets:
        project, name = target.split("/", 1)
        try:
            worker = await runtime.open(project, name)
        except Exception as error:  # noqa: BLE001 - report and keep serving others
            print(f"[fail] {target}: {error}", flush=True)
            continue
        opened.append((target, worker))
        print(f"[ok]   {target}  {worker.url}", flush=True)

    if not opened:
        print("No tools opened.", flush=True)
        await runtime.shutdown()
        return

    print("\nOpen the URLs above. Press Ctrl-C to stop.\n", flush=True)
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runtime.shutdown()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: serve-tools.py <project>/<name> [...]")
    try:
        asyncio.run(main(sys.argv[1:]))
    except KeyboardInterrupt:
        pass
