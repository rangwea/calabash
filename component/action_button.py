"""Shared light outline actions for the desktop shell."""

from nicegui import ui

ACTION_CSS = """
.calabash-action.q-btn {
    width: 30px; height: 30px; min-width: 30px; min-height: 30px;
    padding: 6px; border-radius: 6px; color: var(--app-icon);
}
.calabash-action svg { display: block; width: 18px; height: 18px; }
.calabash-action.calabash-action-text { width: auto; padding: 4px 8px; }
.calabash-action-text .q-btn__content { gap: 6px; }
.calabash-action:hover, .calabash-action[aria-pressed="true"] {
    background: var(--app-hover); color: var(--app-text);
}
.calabash-action:focus-visible { outline: 2px solid var(--app-primary); outline-offset: 2px; }
.calabash-action.calabash-action-compact {
    width: 28px; height: 28px; min-width: 28px; min-height: 28px;
    padding: 7px; color: var(--app-icon);
}
.calabash-action-compact svg { width: 14px; height: 14px; }
.calabash-action.calabash-action-compact:hover { color: var(--app-text); background: var(--app-hover); }
"""

ICONS = {
    "send": '<path d="M12 21V3m-7 7 7-7 7 7"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2"/>',

    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "edit": '<path d="m15 4 5 5M4 20l5-1L21 7l-5-5L4 14Z"/>',
    "pin": '<path d="m9 3 12 12-5 1-3 5-4-7-7-4 5-3ZM9 15l-6 6"/>',
    "settings": '<path d="M19.37 10.16 L21.38 10.51 L21.38 13.49 L19.37 13.84 L18.51 15.91 L19.69 17.58 L17.58 19.69 L15.91 18.51 L13.84 19.37 L13.49 21.38 L10.51 21.38 L10.16 19.37 L8.09 18.51 L6.42 19.69 L4.31 17.58 L5.49 15.91 L4.63 13.84 L2.62 13.49 L2.62 10.51 L4.63 10.16 L5.49 8.09 L4.31 6.42 L6.42 4.31 L8.09 5.49 L10.16 4.63 L10.51 2.62 L13.49 2.62 L13.84 4.63 L15.91 5.49 L17.58 4.31 L19.69 6.42 L18.51 8.09 Z"/><circle cx="12" cy="12" r="3.2"/>',
    "back": '<path d="m10 5-7 7 7 7M3 12h18"/>',

    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
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



def app_icon(name):
    return ui.html('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + '</svg>').classes('app-icon shrink-0')


def menu_item(icon, label, callback, *, danger=False):
    with ui.menu_item(on_click=callback).props('role=menuitem').classes('app-menu-item ' + ('menu-danger' if danger else '')) as item:
        with ui.item_section().props('avatar'):
            app_icon(icon)
        ui.item_section(label)
    return item
