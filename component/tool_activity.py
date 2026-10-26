"""Keep the browser leave warning in sync with real, host-managed jobs."""

from nicegui import ui

from service.tools import tool_activity


def install_activity_monitor():
    client = ui.context.client
    if getattr(client, "calabash_activity_monitor", False):
        return
    client.calabash_activity_monitor = True
    previous = {"busy": None}

    def update():
        tool_activity.check_stop_request()
        busy = bool(tool_activity.active_count())
        if client.has_socket_connection and busy != previous["busy"]:
            client.run_javascript("window.calabashToolRuns?.setBusy(" + ("true" if busy else "false") + ")")
            previous["busy"] = busy

    ui.timer(0.25, update)
