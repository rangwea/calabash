"""Keyboard and pointer activation for rows with independent child actions."""


def activate_row(element, callback, label):
    element._props.update(role='button', tabindex=0, **{'aria-label': label})
    element.on('click', callback, js_handler="(event) => { if (event.target.closest('button, a, input, textarea, .q-menu')) return; emit(); }")
    element.on('keydown', callback, js_handler="(event) => { if (event.target !== event.currentTarget || !['Enter', ' '].includes(event.key)) return; event.preventDefault(); emit(); }")
    return element
