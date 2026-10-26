"""Desktop lifecycle acceptance fixture; gates a simulated file write manually."""

import asyncio

from nicegui import run, ui

from component.tool_results import ToolJobStatus, ToolResults
from service.tools.tool_jobs import ToolJobs


def main():
    gate = asyncio.Event()
    jobs = ToolJobs([1, 2, 3])
    field = ui.input("Output label", value="Example").props("outlined dense hide-bottom-space")
    start = ui.button("Start batch", icon="play_arrow")
    ui.button("Finish current item", on_click=gate.set)
    ui.link("Leave tool", "/")
    status = ToolJobStatus(jobs, controls=(field, start))
    results = ToolResults()

    async def handle(value):
        await gate.wait()
        key = await run.io_bound(results.outputs.write, f"item-{value}.txt", lambda path: path.write_text("complete"))
        results.refresh()
        return key

    start.on_click(lambda: status.run(handle))
