export function installProbe(win, report) {
  const doc = win.document;
  const ids = new Map();
  const counters = new WeakMap();
  let sequence = 0, sent = 0;
  const clean = value => String(value ?? '').slice(0, 1200);
  const route = value => {
    try { const url = new URL(value, win.location.href); return url.protocol === 'file:' ? '[local-file-url]' : url.origin === win.location.origin ? url.pathname.slice(0, 160) : '[external-origin]'; }
    catch (_) { return '[invalid-url]'; }
  };
  const emit = (kind, message, extra = {}) => { if (sent++ < 40) report({ kind, message: clean(message), ...extra }); };
  const visible = element => element.isConnected && element.getClientRects().length > 0 && win.getComputedStyle(element).visibility !== 'hidden';
  // The probe runs only in the isolated tool frame. Include Element Plus
  // dialogs/popovers teleported outside #app, never the host workspace.
  const root = () => doc.body || doc.querySelector('.calabash-tool');
  const idFor = element => { if (!counters.has(element)) counters.set(element, 'e' + (++sequence)); const id = counters.get(element); ids.set(id, element); return id; };
  const blocked = element => element.matches('input[type=password],input[type=file],input[type=hidden]') || element.closest('[data-private], [data-sensitive]') || /password|secret|token|api[_ -]?key|authorization|密钥|密码|令牌/i.test([element.name, element.id, element.getAttribute('aria-label'), element.getAttribute('placeholder'), element.labels?.[0]?.textContent].join(' '));
  const name = element => clean(element.getAttribute('aria-label') || element.labels?.[0]?.textContent || element.textContent || element.getAttribute('placeholder') || '').slice(0, 120);
  const describe = element => ({ id: idFor(element), tag: element.tagName.toLowerCase(), role: element.getAttribute('role') || '', label: name(element), enabled: !element.disabled, input_type: element.type || '', editable: !blocked(element) && !element.readOnly });
  const snapshot = () => {
    const host = root();
    if (!host) return { error: 'Tool content is not mounted' };
    ids.clear();
    const nodes = [...host.querySelectorAll('button,input,textarea,select,[role=button],[role=tab]')].filter(visible).slice(0, 100);
    const media = [...host.querySelectorAll('audio,video')].slice(0, 10).map(element => ({ id: idFor(element), paused: element.paused, ended: element.ended, current_time: Number.isFinite(element.currentTime) ? element.currentTime : null, duration: Number.isFinite(element.duration) ? element.duration : null, ready_state: element.readyState, network_state: element.networkState, error_code: element.error?.code || null, source: route(element.currentSrc || element.src || ''), muted: element.muted }));
    // Never serialize input values, page HTML, hidden contents or file paths.
    const texts = [];
    const walker = doc.createTreeWalker(host, win.NodeFilter.SHOW_TEXT);
    let node, length = 0;
    while ((node = walker.nextNode()) && length < 1600) {
      const parent = node.parentElement;
      if (parent && visible(parent) && !parent.closest('script,style,input,textarea,[data-private],[data-sensitive]')) {
        const text = node.textContent.trim();
        if (text) { texts.push(text); length += text.length; }
      }
    }
    return { text: texts.join(' ').slice(0, 1600), elements: nodes.filter(element => !blocked(element)).map(describe), media, horizontal_overflow: doc.documentElement.scrollWidth > win.innerWidth + 2 };
  };
  const operate = request => {
    const element = ids.get(request.element_id);
    if (!element || !root()?.contains(element) || !visible(element) || blocked(element) || element.disabled || name(element) !== request.expected_label) return { error: 'Target expired, hidden or forbidden; inspect again' };
    if (request.action === 'click') {
      if (!element.matches('button,[role=button],[role=tab],input[type=checkbox],input[type=radio]')) return { error: 'Only local tool controls may be clicked' };
      element.click();
    } else if (request.action === 'fill') {
      if (!element.matches('input,textarea') || element.readOnly || ['checkbox','radio','submit','button'].includes(element.type)) return { error: 'Target is not an editable text control' };
      const prototype = element.tagName === 'TEXTAREA' ? win.HTMLTextAreaElement.prototype : win.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, clean(request.value));
      element.dispatchEvent(new win.Event('input', { bubbles: true }));
      element.dispatchEvent(new win.Event('change', { bubbles: true }));
    } else return { error: 'Unsupported operation' };
    return { dispatched: true, verified: false };
  };
  const onError = event => {
    if (event.target?.matches?.('audio,video')) emit('media_error', 'Media resource failed', { code: event.target.error?.code || 0, source: route(event.target.currentSrc || event.target.src) });
    else if (event.target !== win && event.target?.src) emit('resource_error', 'Resource failed', { source: route(event.target.src) });
    else emit('javascript_error', event.message || 'JavaScript error', { stack: clean(event.error?.stack), line: Number(event.lineno) || 0 });
  };
  const onRejection = event => emit('unhandled_rejection', event.reason?.message || 'Unhandled promise rejection', { stack: clean(event.reason?.stack) });
  win.addEventListener('error', onError, true);
  win.addEventListener('unhandledrejection', onRejection);
  const originalError = win.console.error;
  const wrappedError = (...args) => {
    const first = args.find(value => typeof value === 'string' || value instanceof Error);
    if (first !== undefined) emit('console_error', typeof first === 'string' ? first : first.message);
    return originalError.apply(win.console, args);
  };
  win.console.error = wrappedError;
  const originalFetch = win.fetch;
  const wrappedFetch = async (...args) => {
    try { const response = await originalFetch.apply(win, args); if (!response.ok) emit('request_failed', 'HTTP request failed', { status: response.status, source: route(typeof args[0] === 'string' ? args[0] : args[0]?.url) }); return response; }
    catch (error) { emit('request_failed', 'Network request failed', { source: route(typeof args[0] === 'string' ? args[0] : args[0]?.url) }); throw error; }
  };
  win.fetch = wrappedFetch;
  return { snapshot, operate, dispose() { win.removeEventListener('error', onError, true); win.removeEventListener('unhandledrejection', onRejection); if (win.fetch === wrappedFetch) win.fetch = originalFetch; if (win.console.error === wrappedError) win.console.error = originalError; ids.clear(); } };
}

export default {
  template: '<span hidden aria-hidden="true"></span>',
  mounted() { this.probe = installProbe(window, event => this.$emit('diagnostic', event)); window.calabashPreviewProbe = this.probe; },
  beforeUnmount() { this.probe?.dispose(); if (window.calabashPreviewProbe === this.probe) delete window.calabashPreviewProbe; },
};
