"""
project: demo
name: capability_preflight_test
description: Acceptance fixture for declared capabilities and manual retry
creator: Calabash
created_at: 2026-10-21
updated_at: 2026-10-21
tags: test,capabilities
requires: media.ffmpeg>=9.0.2
"""

from pathlib import Path

from nicegui import ui


def main():
    marker = Path.home() / ".calabash" / "capability-acceptance-ran.txt"
    marker.write_text("main executed after manual retry", encoding="utf-8")
    ui.label("Capability preflight passed").classes("text-lg font-semibold")
    ui.label("FFmpeg is ready. Tool main() has now executed.").classes("text-sm text-gray-500")


if __name__ in {"__main__", "__mp_main__"}:
    main()
    ui.run()
