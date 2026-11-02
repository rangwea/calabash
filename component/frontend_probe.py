"""Preview-only collector; agents access it exclusively through consent-gated services."""

from nicegui import ui


class FrontendProbe(ui.element, component='frontend_probe.js'):
    def __init__(self, session):
        super().__init__()
        self.on('diagnostic', lambda event: session.capture(event.args))
