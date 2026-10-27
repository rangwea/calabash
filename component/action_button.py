"""Shared light outline actions for the desktop shell."""

from nicegui import ui

ACTION_CSS = """
.calabash-action.q-btn {
    width: 30px; height: 30px; min-width: 30px; min-height: 30px;
    padding: 6px; border-radius: 6px; color: #818b98;
}
.calabash-action svg { display: block; width: 18px; height: 18px; }
.calabash-action.calabash-action-text { width: auto; padding: 4px 8px; }
.calabash-action-text .q-btn__content { gap: 6px; }
.calabash-action:hover, .calabash-action[aria-pressed="true"] {
    background: #f3f4f6; color: #66717f;
}
.calabash-action:focus-visible { outline: 2px solid #b6c3d0; outline-offset: 2px; }
.calabash-action.calabash-action-compact {
    width: 28px; height: 28px; min-width: 28px; min-height: 28px;
    padding: 7px; color: #969faa;
}
.calabash-action-compact svg { width: 14px; height: 14px; }
.calabash-action.calabash-action-compact:hover { color: #7b8591; background: #eceff3; }
"""

ICONS = {
    "folder": '<path d="M3 8V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    "copy": '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4"/>',
    "upload": '<path d="M12 16V4m-5 5 5-5 5 5M4 16v4h16v-4"/>',
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z"/>',
    "play": '<path d="m8 4 13 8-13 8Z"/>',
    "delete": '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
    "attach": '<path d="m8 12 7-7a4 4 0 0 1 6 6L10 22a6 6 0 0 1-8-8L13 3M6 16 17 5"/>',
    "preview": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2Z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/>',
    "refresh": '<path d="M20 7v5h-5M20 12a8 8 0 1 0-2.3 5.7"/>',
    "open": '<path d="M14 3h7v7M21 3 11 13M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
}


def action_button(icon, label, callback, *, leave=False, text=False, compact=False):
    ui.add_css(ACTION_CSS, shared=True)
    button = ui.button(on_click=callback, color=None).props("flat dense no-caps" + (" data-tool-leave" if leave else "")).classes("calabash-action shrink-0")
    button._props['aria-label'] = label
    if text:
        button.classes('calabash-action-text')
    if compact:
        button.classes('calabash-action-compact')
    with button:
        ui.html('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[icon] + '</svg>')
        if text:
            ui.label(label).classes('text-sm')
        tip = ui.tooltip(label)
    return button, tip

