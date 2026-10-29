"""Fluent-inspired application chrome; generated tools keep their own theme."""

from pathlib import Path

from nicegui import app, ui

from core.tool_theme import TOOL_THEME_CSS

BRAND_COLORS = {
    "primary": "#0F6CBD",
    "secondary": "#6950A1",
    "tertiary": "#8B5CF6",
    "accent": "#8B5CF6",
    "positive": "#107C41",
    "negative": "#B4233B",
    "warning": "#9A5700",
    "info": "#0284C7",
}

GLOBAL_CSS = """
<style>
    html, body {
        margin: 0 !important;
        padding: 0 !important;
    }

    body {
        min-height: 100vh;
        background: var(--app-background) !important;
        color: var(--app-text) !important;
        font-family: var(--app-font);
    }

    *, *::before, *::after { box-sizing: border-box; }
    .nicegui-content { margin: 0 !important; padding: 0 !important; }
    body { font-size: 14px; line-height: 1.5; }
    .app-shell { background: var(--app-background); color: var(--app-text); }
    .app-shell .app-sidebar-host { background: var(--app-sidebar); }
    .app-shell .app-workspace-tabs {
        height: 40px; min-height: 40px; max-height: 40px; padding: 3px 8px;
        background: var(--app-background); border-color: var(--app-border);
    }
    .app-workspace-tabs .workspace-list-entry.q-btn {
        height: 32px; min-height: 32px; border: 0; padding: 4px 8px;
        color: var(--app-muted); background: transparent;
    }
    .app-workspace-tabs .workspace-list-entry .text-sm { font-size: 13px; }
    .app-workspace-tabs .workspace-list-entry svg { width: 16px; height: 16px; }
    .app-workspace-tabs .workspace-list-entry.q-btn:hover { background: var(--app-hover); color: var(--app-text); }
    /* Keep tab overflow scrollable without a second visual baseline under the active indicator. */
    .app-workspace-tabs .workspace-tab-strip { scrollbar-width: none; }
    .app-workspace-tabs .workspace-tab-strip::-webkit-scrollbar { display: none; }
    .app-workspace-tabs .workspace-tab {
        height: 32px; min-height: 32px; padding: 0 4px 0 0;
        border-radius: 4px; color: var(--app-muted); position: relative;
    }
    .app-workspace-tabs .workspace-tab:hover { background: var(--app-hover); }
    .app-workspace-tabs .workspace-tab-active { color: var(--app-primary); }
    .app-workspace-tabs .workspace-tab-active::after {
        content: ''; position: absolute; bottom: 0; left: 10px; right: 10px;
        height: 2px; background: var(--app-primary); border-radius: 2px; pointer-events: none;
    }
    .app-workspace-tabs .workspace-tab-button.q-btn {
        color: inherit; height: 32px; min-height: 32px; padding: 4px 10px;
        font-size: 13px; line-height: 20px;
    }
    .app-workspace-tabs .workspace-tab-button .q-btn__content {
        display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .app-workspace-tabs .workspace-tab-button .q-btn__content > .block {
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .app-workspace-tabs .workspace-tab .calabash-action.q-btn {
        width: 24px; min-width: 24px; height: 24px; min-height: 24px;
        padding: 5px; color: var(--app-icon); border-radius: 4px;
    }
    .app-workspace-tabs .workspace-tab .calabash-action.q-btn:hover {
        background: var(--app-border); color: var(--app-text);
    }
    .app-workspace-tabs .workspace-tab .calabash-action svg { width: 14px; height: 14px; }
    .app-shell .app-tool-group { padding: 16px; background: var(--app-surface); border: 1px solid var(--app-border); border-radius: var(--app-radius-panel); }
    .app-shell .app-tool-row { border-color: var(--app-border); border-radius: 6px; }
    .app-shell .app-tool-row:hover { background: var(--app-primary-light); }
    .app-shell .app-tool-icon { background: var(--app-primary-light); color: var(--app-primary); }
    .app-shell .app-tool-tag { background: var(--app-background); color: var(--app-muted); border: 1px solid var(--app-border); }
    .app-chat-toolbar, .app-preview-toolbar { background: var(--app-surface); border-color: var(--app-border); min-height: 44px; }
    .app-shell .app-canvas { background: var(--app-background); }
    .app-shell .app-title { font-size: 24px; font-weight: 650; line-height: 1.3; letter-spacing: -.02em; }
    .app-shell .app-muted { color: var(--app-muted); }
    .app-shell .app-section-title { font-size: 14px; font-weight: 600; color: var(--app-text); }
    .app-settings-section { padding: 20px; border: 1px solid var(--app-border); border-radius: var(--app-radius-panel); background: var(--app-surface); }
    .app-setting-row { border-color: var(--app-border); }
    .app-shell :focus-visible, .q-dialog :focus-visible, .conversation-menu :focus-visible {
        outline: 2px solid var(--app-primary); outline-offset: 2px;
    }
    .app-shell .q-btn:focus-visible { outline-offset: 2px; }
    .app-shell .q-btn.bg-primary:hover { background: var(--app-primary-hover) !important; }
    .app-shell .q-btn.bg-primary:active { background: var(--app-primary-pressed) !important; }
    .app-shell .q-btn:not(.calabash-action):not(.q-btn--round):not(.workspace-tab-button) { min-height: var(--app-control-height); }
    .app-shell .q-field--dense:not(.q-field--labeled):not(.q-textarea) .q-field__control,
    .app-shell .q-field--dense:not(.q-field--labeled):not(.q-textarea) .q-field__marginal { min-height: 36px; height: 36px; }
    .app-shell .q-field--dense:not(.q-field--labeled):not(.q-textarea) .q-field__native { min-height: 36px; padding-top: 6px; padding-bottom: 6px; }
    .q-dialog .q-card:not(:where(.calabash-tool *)), .q-menu:not(.conversation-menu) {
        border: 1px solid var(--app-border); border-radius: var(--app-radius-panel); box-shadow: var(--app-shadow-float);
    }
    .q-dialog .q-card:not(:where(.calabash-tool *)) { padding: 24px; }
    .q-menu .q-item { min-height: 36px; font-size: 14px; }
    .q-tooltip { font-size: 12px; line-height: 1.5; border-radius: 4px; }
    @media (prefers-reduced-motion: reduce) { .app-shell *, .app-shell *::before, .app-shell *::after { transition-duration: 0s; animation-duration: 0s; } }


    .app-text-primary { color: var(--app-text) !important; }
    .app-text-secondary { color: var(--app-secondary) !important; }
    .app-bg-primary-light { background-color: var(--app-primary-light) !important; }
    .app-bg-secondary-light { background-color: var(--app-secondary-light) !important; }
    .app-border-primary { border-color: var(--app-primary) !important; }
    .app-border-secondary { border-color: var(--app-secondary) !important; }
    .app-menu-hover:hover { background-color: var(--app-hover) !important; }
    .app-menu-active {
        color: var(--q-primary) !important;
        background-color: var(--app-primary-soft) !important;
        border-left: 3px solid var(--q-primary) !important;
    }

    .nicegui-content .q-card:not(:where(.calabash-tool *)) {
        border: 1px solid var(--app-border);
        border-radius: var(--app-radius-panel);
        background: var(--app-surface);
        box-shadow: none;
        transition: border-color 0.15s ease-in-out;
    }
    .nicegui-content .q-card:not(:where(.calabash-tool *)):hover { border-color: var(--app-border); }

    .nicegui-content .q-btn:not(:where(.calabash-tool *)) {
        border-radius: var(--app-radius-control);
        box-shadow: none;
        font-size: 0.875rem;
        font-weight: 500;
        letter-spacing: 0;
        text-transform: none;
        transition: background-color 0.15s ease-in-out,
            border-color 0.15s ease-in-out, color 0.15s ease-in-out;
    }
    .nicegui-content .q-btn:not(:where(.calabash-tool *)):hover,
    .nicegui-content .q-btn:not(:where(.calabash-tool *)):active { box-shadow: none; transform: none; }

    .nicegui-content .q-field--outlined:not(:where(.calabash-tool *)) .q-field__control {
        border-radius: var(--app-radius-control);
        background: var(--app-surface);
    }
    .nicegui-content .q-field--outlined:not(:where(.calabash-tool *)) .q-field__control::before {
        border-color: var(--app-border);
    }
    .nicegui-content .q-field--outlined:not(:where(.calabash-tool *)).q-field--focused .q-field__control::before {
        border-color: var(--q-primary);
        border-width: 2px;
    }

    .nicegui-content .q-avatar:not(:where(.calabash-tool *)) { background-color: inherit; color: inherit; }
    .nicegui-content .q-avatar:not(:where(.calabash-tool *)).bg-blue-100 { background: var(--app-primary-light); color: var(--app-primary); }
    .nicegui-content .q-avatar:not(:where(.calabash-tool *)).bg-green-100 { background: var(--app-success-soft); color: var(--app-success); }
    .nicegui-content .q-avatar:not(:where(.calabash-tool *)).bg-purple-100 { background: #F3E8FF; color: #7C2D12; }
    .nicegui-content .q-avatar:not(:where(.calabash-tool *)).bg-orange-100 { background: #FED7AA; color: #9A3412; }
    .nicegui-content .q-avatar:not(:where(.calabash-tool *)).bg-red-100 { background: var(--app-danger-soft); color: var(--app-danger); }
    .nicegui-content .q-avatar:not(:where(.calabash-tool *)).bg-yellow-100 { background: var(--app-warning-soft); color: var(--app-warning); }
    .nicegui-content .q-avatar:not(:where(.calabash-tool *)).bg-pink-100 { background: #FCE7F3; color: #BE185D; }
    .nicegui-content .q-avatar:not(:where(.calabash-tool *)).bg-indigo-100 { background: #E0E7FF; color: #3730A3; }
    .nicegui-content .q-avatar:not(:where(.calabash-tool *)).bg-gray-100 { background: #F3F4F6; color: #374151; }

    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: rgba(243, 244, 246, 0.5); }
    ::-webkit-scrollbar-thumb { background: #9CA3AF; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #6B7280; }

    .status-badge {
        display: inline-flex;
        align-items: center;
        padding: 0.25rem 0.5rem;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 500;
        line-height: 1;
    }
    .status-success { background: var(--app-success-soft); color: var(--app-success); }
    .status-warning { background: var(--app-warning-soft); color: var(--app-warning); }
    .status-error { background: var(--app-danger-soft); color: var(--app-danger); }
    .status-info { background: var(--app-primary-light); color: var(--app-primary); }
    .status-neutral { background: #F3F4F6; color: #374151; }

.chat-send.calabash-action.q-btn { color: white; background: var(--app-primary); }
.chat-send.calabash-action.q-btn:hover { color: white; background: var(--app-primary-hover); }
.row-open-target.q-btn { border-radius: inherit; padding: 0; }
.row-open-target.q-btn .q-focus-helper { display: none; }
.row-open-target.q-btn:focus-visible { outline: 2px solid var(--app-primary); outline-offset: -2px; }
.app-icon { display: inline-flex; align-items: center; color: inherit; }
.app-action-menu { padding: 5px; border: 1px solid var(--app-border); border-radius: 8px; background: var(--app-surface); box-shadow: var(--app-shadow-float); min-width: 170px; }
.app-action-menu .q-item { min-height: 34px; padding: 6px 10px; border-radius: 4px; font-size: 13px; }
.app-action-menu .q-item__section--avatar { min-width: 26px; padding-right: 8px; color: var(--app-icon); }
.app-action-menu .menu-danger { color: var(--app-danger); }
.app-tool-row:focus-visible { outline: 2px solid var(--app-primary); outline-offset: -2px; }
.calabash-chat { container: chat-workspace / inline-size; }
.chat-preview-back { display: none !important; }
@container chat-workspace (max-width: 800px) {
    .chat-main:has(~ .chat-preview:not(.hidden)) { display: none !important; }
    .chat-preview { width: 100% !important; flex: 1 1 100%; border-left: 0; }
    .chat-preview-divider { display: none !important; }
    .chat-preview-back { display: inline-flex !important; }
}

</style>
"""


def apply_app_styles() -> None:
    """应用固定品牌色、全局 CSS 和组件默认值。"""
    app.config.quasar_config["brand"].update(BRAND_COLORS)

    field_props = 'outlined hide-bottom-space color="primary"'
    for element in (ui.input, ui.textarea, ui.number, ui.select, ui.date_input):
        element.default_props(field_props)

    ui.button.default_props("no-caps")
    ui.checkbox.default_props('color="primary"')
    ui.radio.default_props('color="primary"')
    ui.switch.default_props('color="primary"')
    ui.avatar.default_props('color=""')

    ui.add_head_html("<style>" + (Path(__file__).resolve().parents[1] / "component/assets/fluent_tokens.css").read_text(encoding="utf-8") + "</style>", shared=True)
    ui.add_head_html(GLOBAL_CSS, shared=True)
    ui.add_head_html("<style>" + TOOL_THEME_CSS + "</style>", shared=True)
    ui.add_head_html("<script>" + (Path(__file__).resolve().parents[1] / "component/context_menu.js").read_text(encoding="utf-8") + "</script>", shared=True)
    ui.add_head_html("<script>" + (Path(__file__).resolve().parents[1] / "component/tool_activity.js").read_text(encoding="utf-8") + "</script>", shared=True)
