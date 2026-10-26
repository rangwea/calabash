(() => {
  if (window.calabashContextMenuInstalled) return;
  window.calabashContextMenuInstalled = true;
  // Cancel only the native menu; custom menu listeners still receive the event.
  document.addEventListener('contextmenu', event => event.preventDefault(), true);
})();
