// Shared by the top-level page and same-origin tool previews.
(() => {
  let root = window;
  try { if (window.top.location.origin === location.origin) root = window.top; } catch (_) {}
  if (root.calabashToolRuns) {
    window.calabashToolRuns = root.calabashToolRuns;
    return;
  }
  const state = {
    busy: false,
    setBusy(value) { state.busy = Boolean(value); },
    allowLeave() {
      if (!state.busy) return true;
      const english = root.document.documentElement.lang.startsWith('en');
      return root.confirm(english
        ? 'A tool is still running. It will continue in the background. Leave this view?'
        : '工具仍在运行，离开后会继续在后台处理。确定离开当前页面？');
    },
  };
  root.calabashToolRuns = state;
  root.addEventListener('beforeunload', (event) => {
    if (!state.busy) return;
    event.preventDefault();
    event.returnValue = '';
  });
  root.document.addEventListener('click', (event) => {
    const action = event.target.closest('[data-tool-leave], a[href]');
    if (!action || !state.busy) return;
    if (action.tagName === 'A' && (action.target === '_blank' || action.getAttribute('href')?.startsWith('#'))) return;
    if (!state.allowLeave()) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
})();
