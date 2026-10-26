"""
project: showcase
name: Media workspace
description: Real video metadata, local preview, audio clipping and batch WAV/FLAC export.
creator: Calabash showcase
created_at: 2026-10-26
updated_at: 2026-10-26
tags: video,audio,batch
requires: media.ffmpeg>=9.0.2
"""

import tempfile
import wave
from pathlib import Path

from nicegui import run, ui

from component.tool_files import ToolFileInput
from component.tool_results import ToolJobStatus, ToolResults
from service.capabilities.media_runtime import MediaRuntime
from service.tools.tool_jobs import ToolJobs


def extract_clip(media, source, destination, start, end):
    with tempfile.TemporaryDirectory(prefix="calabash-clip-") as temporary:
        raw = Path(temporary) / "audio.wav"
        media.extract_audio(source, raw)
        clipped = (
            destination
            if destination.suffix == ".wav"
            else Path(temporary) / "clipped.wav"
        )
        with wave.open(str(raw), "rb") as incoming:
            rate = incoming.getframerate()
            if end > incoming.getnframes() / rate or end <= start:
                raise ValueError("Invalid interval")
            incoming.setpos(round(start * rate))
            with wave.open(str(clipped), "wb") as outgoing:
                outgoing.setparams(incoming.getparams())
                outgoing.writeframes(incoming.readframes(round((end - start) * rate)))
        if destination.suffix == ".flac":
            media.convert(clipped, destination, profile="flac")


def main():
    english = getattr(ui.context.client, "demo_language", "zh") == "en"
    tr = lambda zh, en: en if english else zh
    media = MediaRuntime()
    state = {"source": None, "metadata": None}
    with ui.column().classes("w-full gap-4"):
        with ui.row().classes("w-full items-center justify-between gap-3"):
            with ui.column().classes("gap-1"):
                ui.label(
                    tr("把声音，从视频里留下。", "Keep the audio. Leave the rest.")
                ).classes("text-lg font-semibold")
                ui.label(
                    tr(
                        "本地视频预览、区间截取与批量音频导出",
                        "Local preview, audio intervals and batch exports",
                    )
                ).classes("text-xs text-gray-500")
            ui.label("FFmpeg · " + tr("能力插件已安装", "Plugin installed")).classes(
                "text-xs text-emerald-700 bg-emerald-50 px-2 py-1 rounded"
            )
        with ui.grid(columns=12).classes("w-full gap-6"):
            with ui.column().classes("col-span-6 min-w-0 gap-3"):
                ui.label(tr("输入文件", "Input files")).classes("text-sm font-semibold")
                inputs = ToolFileInput()

                async def inspect():
                    if not inputs.paths or status.jobs.running:
                        return
                    probe.disable()
                    try:
                        paths = inputs.freeze()
                        info = await run.io_bound(media.probe, paths[0])
                        state.update(source=paths[0], metadata=info)
                        preview.refresh()
                    except (OSError, ValueError):
                        ui.notify(
                            tr("无法读取媒体文件", "Cannot inspect this media file"),
                            type="negative",
                        )
                    finally:
                        inputs.unfreeze()
                        probe.enable()

                probe = (
                    ui.button(
                        tr("读取媒体信息", "Inspect media"),
                        icon="o_video_file",
                        on_click=inspect,
                    )
                    .props("outline dense color=grey-7")
                    .props("data-testid=media-inspect")
                )
            with ui.column().classes("col-span-6 min-w-0 gap-2"):

                @ui.refreshable
                def preview():
                    if not state["source"]:
                        with ui.column().classes(
                            "w-full h-52 bg-gray-100 rounded-md items-center justify-center gap-3"
                        ):
                            ui.icon("play_circle_outline", size="36px").classes(
                                "text-gray-400"
                            )
                            ui.label(
                                tr("选择视频以预览", "Choose a video to preview")
                            ).classes("text-xs text-gray-400")
                        return
                    ui.video(str(state["source"])).props(
                        "controls preload=auto"
                    ).classes("w-full h-48 bg-gray-900 rounded-md")
                    info = state["metadata"]
                    video = next(
                        (
                            stream
                            for stream in info["streams"]
                            if stream["codec_type"] == "video"
                        ),
                        {},
                    )
                    duration = float(info.get("format", {}).get("duration", 0))
                    with ui.row().classes(
                        "w-full justify-between items-center text-xs text-gray-500"
                    ):
                        ui.label(Path(state["source"]).name)
                        ui.label(
                            f"{video.get('width', 0)} × {video.get('height', 0)} · {duration:.1f}s"
                        )

                preview()
        with ui.column().classes("w-full border-t border-gray-200 pt-4 gap-3"):
            ui.label(tr("音频导出设置", "Audio export settings")).classes(
                "text-sm font-semibold"
            )
            with ui.grid(columns=4).classes("w-full gap-3 items-end"):
                start_time = (
                    ui.number(
                        tr("开始时间（秒）", "Start (seconds)"),
                        value=1,
                        min=0,
                        step=0.5,
                    )
                    .props("outlined dense hide-bottom-space")
                    .classes("w-full")
                    .props("data-testid=media-start")
                )
                end_time = (
                    ui.number(
                        tr("结束时间（秒）", "End (seconds)"),
                        value=5,
                        min=0.5,
                        step=0.5,
                    )
                    .props("outlined dense hide-bottom-space")
                    .classes("w-full")
                    .props("data-testid=media-end")
                )
                output = (
                    ui.select(
                        {"wav": "WAV · PCM", "flac": "FLAC · Lossless"},
                        value="wav",
                        label=tr("输出格式", "Output format"),
                    )
                    .props("outlined dense hide-bottom-space")
                    .classes("w-full")
                    .props("data-testid=media-format")
                )

                async def execute():
                    if status.jobs.running or not inputs.paths:
                        return
                    start, end = (
                        float(start_time.value or 0),
                        float(end_time.value or 0),
                    )
                    if start < 0 or end <= start:
                        ui.notify(
                            tr(
                                "结束时间必须大于开始时间",
                                "End must be later than start",
                            ),
                            type="warning",
                        )
                        return
                    suffix = output.value
                    paths = tuple(inputs.paths)
                    status.jobs = ToolJobs(paths, owner=status.jobs.owner)
                    results.start_run()
                    results.container.set_visibility(True)

                    async def handle(path):
                        key = await run.io_bound(
                            results.outputs.write,
                            Path(path).stem + f"-clip.{suffix}",
                            lambda destination: extract_clip(
                                media, path, destination, start, end
                            ),
                        )
                        results.refresh()
                        return key

                    await status.run(handle)

                start = (
                    ui.button(
                        tr("批量提取音频", "Extract audio"),
                        icon="graphic_eq",
                        on_click=execute,
                    )
                    .props("dense unelevated color=primary")
                    .classes("h-10")
                    .props("data-testid=media-run")
                )
        status = ToolJobStatus(
            ToolJobs([]),
            inputs=(inputs,),
            controls=(start, start_time, end_time, output, probe),
        )
        results = ToolResults()
        results.container.set_visibility(False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
    ui.run(title="Calabash showcase", reload=False, show=False)
