"""Open a published tool through the real runtime and screenshot it.

This is the honest-capture path: it loads the actual published build with the
real Python backend behind the real loopback origin, then screenshots what the
browser renders. Nothing in the frame is drawn by hand.

What it cannot do on its own: it captures the tool pane only. The Electron chat
shell around it is not part of these frames, so they must not be presented as a
full desktop recording.

Run it with a disposable HOME so real tools and data stay out of reach:

    HOME=$(mktemp -d) ... # copy or create the tools you want to capture

Usage:
    .venv/bin/python3 website/demos/render-real.py <out-dir> default/video_clip_trimmer
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

async def capture(url: str, destination: Path) -> str:
    """Screenshot a live page with Playwright in a separate process.

    This must stay asynchronous: the tool server runs on the caller's event
    loop, so a blocking wait would deadlock the very page being captured.
    """
    process = await asyncio.create_subprocess_exec(
        'node',
        str(ROOT / 'website' / 'demos' / 'capture-url.cjs'),
        url,
        str(destination),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=180)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(f"Capture timed out for {destination.name}") from None
    if process.returncode or not destination.exists():
        raise RuntimeError(f"Capture failed for {destination.name}: {stderr.decode()[-500:]}")
    return stdout.decode().strip()


async def main(targets: list[str], output: Path) -> None:
    # Import the logger before any run is started. core.logger.setup_logger()
    # calls logger.remove() at import time, which would otherwise drop a sink
    # that a running tool had already registered.
    import core.logger  # noqa: F401
    from service.tools.tool_workers import ToolWorkers

    output.mkdir(parents=True, exist_ok=True)
    workers = ToolWorkers()
    for target in targets:
        project, name = target.split("/", 1)
        print(f"opening {target} ...", flush=True)
        worker = await workers.open(project, name)
        try:
            print(f"  live at {worker.url.split('?')[0]}", flush=True)
            destination = output / f"{name}.png"
            detail = await capture(worker.url, destination)
            print(f"  wrote {destination} {detail}", flush=True)
        finally:
            # shutdown() already closes each worker; closing twice trips the
            # run-log reference count and masks the real outcome.
            await workers.shutdown()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("Usage: render-real.py <out-dir> <project>/<name> [...]")
    asyncio.run(main(sys.argv[2:], Path(sys.argv[1])))
