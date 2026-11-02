"""
project: calabash
name: media_workspace_template
description: 深色媒体工作区骨架：局部菜单、内容与设置，不模拟文件或播放结果
creator: auto-generator
created_at: 2026-10-29
updated_at: 2026-10-29
tags: 媒体, 深色主题, 工作区
requires:
"""

from nicegui import ui


def main() -> None:
    ui.add_css("""
    .media-demo {
        --tool-accent:#a6e1d8; --tool-accent-soft:#233e42; --tool-on-accent:#112629;
        --tool-canvas:#142326; --tool-surface:#1b2d31; --tool-surface-muted:#23383d;
        --tool-text:#eff8f7; --tool-muted:#afc4c6; --tool-border:#385157;
        --q-primary:var(--tool-accent); background:var(--tool-canvas);
        color:var(--tool-text); padding:24px; border-radius:12px;
    }
    .media-demo .media-layout { display:grid; grid-template-columns:170px minmax(0,1fr); gap:24px; width:100%; }
    .media-demo .media-cover { width:110px; height:110px; border-radius:24px; background:linear-gradient(135deg,#3c6771,#56476f); display:grid; place-items:center; color:#e4f5f3; }
    .media-demo .media-nav { color:var(--tool-muted); justify-content:flex-start; width:100%; }
    .media-demo .media-selected { background:var(--tool-accent-soft); color:var(--tool-accent); }
    .media-demo .q-field, .media-demo .q-field__label, .media-demo .q-field__native, .media-demo .q-field__marginal { color:var(--tool-text); }
    @media(max-width:640px) { .media-demo {padding:16px;} .media-demo .media-layout {grid-template-columns:minmax(0,1fr);} .media-demo .media-menu {flex-direction:row;flex-wrap:wrap;} .media-demo .media-nav {width:auto;} }
    """)
    with ui.column().classes("media-demo w-full min-w-0 gap-5"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("声音工作室").classes("tool-title")
            ui.label("工作区骨架 · 未连接媒体").classes("tool-muted text-xs")
        with ui.element("div").classes("media-layout"):
            with ui.column().classes("media-menu gap-2"):
                nav_buttons = {}
                for name, icon in [("媒体库", "library_music"), ("工作区设置", "tune")]:
                    nav_buttons[name] = (
                        ui.button(
                            name, icon=icon, on_click=lambda _, name=name: switch(name)
                        )
                        .props("flat")
                        .classes("media-nav")
                    )
            with ui.column().classes("min-w-0 w-full gap-4"):
                with ui.column().classes(
                    "tool-panel w-full items-center gap-4 py-10"
                ) as library:
                    with ui.element("div").classes("media-cover"):
                        ui.icon("graphic_eq", size="48px")
                    ui.label("为你的声音留一个工作区").classes(
                        "tool-subtitle text-center"
                    )
                    ui.label(
                        "这里还没有媒体文件。接入 ToolFileInput 后，在此展示真实文件与播放器。"
                    ).classes("tool-muted text-center max-w-md")
                    ui.label("模板不模拟播放，不会读取本机音乐目录。").classes(
                        "tool-muted text-xs text-center"
                    )
                with ui.column().classes("tool-panel w-full gap-4") as settings:
                    ui.label("工作区设置").classes("tool-subtitle")
                    ui.switch(
                        "紧凑模式",
                        on_change=lambda e: (
                            workspace.classes(toggle="gap-2", remove="gap-4")
                            if e.value
                            else workspace.classes(add="gap-4", remove="gap-2")
                        ),
                    ).props("color=primary")
                    ui.label(
                        "设置仅影响当前实例；需要跨次保存时接入工具参数存储。"
                    ).classes("tool-muted")
                with ui.row().classes(
                    "tool-panel w-full items-center gap-3"
                ) as workspace:
                    ui.icon("music_note", size="24px").classes("tool-text-accent")
                    with ui.column().classes("flex-1 min-w-0 gap-1"):
                        ui.label("尚未选择音频").classes("font-medium")
                        ui.label("选择真实媒体后再启用播放控制").classes(
                            "tool-muted text-xs"
                        )
                    play_button = (
                        ui.button(icon="play_arrow")
                        .props("round flat color=primary")
                        .tooltip("尚未选择音频")
                    )
                    play_button.disable()

        def switch(name: str) -> None:
            library.set_visibility(name == "媒体库")
            settings.set_visibility(name == "工作区设置")
            for label, button in nav_buttons.items():
                button.classes(
                    add="media-selected" if label == name else "",
                    remove="" if label == name else "media-selected",
                )

        switch("媒体库")
