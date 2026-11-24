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

async def capture(url: str, destination: Path, recipe: str = "", fixtures: Path | None = None) -> str:
    """Screenshot a live page with Playwright in a separate process.

    This must stay asynchronous: the tool server runs on the caller's event
    loop, so a blocking wait would deadlock the very page being captured.
    """
    script = 'record-real.cjs' if recipe else 'capture-url.cjs'
    argv = [url, str(destination)]
    if recipe:
        argv += [recipe, str(fixtures or "")]
    process = await asyncio.create_subprocess_exec(
        'node',
        str(ROOT / 'website' / 'demos' / script),
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    budget = 600 if recipe else 180
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=budget)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(f"Capture timed out for {destination.name}") from None
    produced = (destination / "frames.json").exists() if recipe else destination.exists()
    if process.returncode or not produced:
        raise RuntimeError(f"Capture failed for {destination.name}: {stderr.decode()[-500:]}")
    return stdout.decode().strip()


async def main(targets: list[str], output: Path, recipe: str = "", fixtures: Path | None = None) -> None:
    # Import the logger before any run is started. core.logger.setup_logger()
    # calls logger.remove() at import time, which would otherwise drop a sink
    # that a running tool had already registered.
    import core.logger  # noqa: F401
    from service.tools.tool_workers import ToolWorkers

    output.mkdir(parents=True, exist_ok=True)
    for target in targets:
        project, name = target.split("/", 1)
        print(f"opening {target} ...", flush=True)
        # A fresh runtime per tool: shutdown() marks the whole runtime as
        # stopping, so reusing one would reject the next open().
        workers = ToolWorkers()
        worker = await workers.open(project, name)
        try:
            print(f"  live at {worker.url.split('?')[0]}", flush=True)
            destination = output / (name if recipe else f"{name}.png")
            detail = await capture(worker.url, destination, recipe, fixtures)
            print(f"  wrote {destination} {detail}", flush=True)
        finally:
            await workers.shutdown()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("Usage: render-real.py <out-dir> <project>/<name> [...] [--recipe NAME --fixtures DIR]")
    argv = sys.argv[1:]
    recipe, fixtures = "", None
    if "--recipe" in argv:
        at = argv.index("--recipe")
        recipe = argv[at + 1]
        del argv[at : at + 2]
    if "--fixtures" in argv:
        at = argv.index("--fixtures")
        fixtures = Path(argv[at + 1])
        del argv[at : at + 2]
    asyncio.run(main(argv[1:], Path(argv[0]), recipe, fixtures))
