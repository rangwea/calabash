// Host-owned runtime boundary, also injected into previously built tool pages.
(() => {
  if (window.__calabashRuntimeGuard) return
  window.__calabashRuntimeGuard = true
  const original = window.fetch.bind(window)
  const en = typeof guardLanguage !== 'undefined' && guardLanguage === 'en'
  const friendly = en ? 'The tool could not complete this action. Please try again or ask AI to fix it.' : '工具暂时未能完成操作，请重试或让 AI 帮你修复'
  const sent = new Set()
  function report(kind, path = '', status = 0, needsRepair = true, requestId = '') {
    const key = kind + path + status
    if (sent.has(key)) return
    if (sent.size >= 20) return
    sent.add(key)
    if (needsRepair && window.parent !== window) window.parent.postMessage({kind: 'calabash-tool-issue'}, '*')
    void original('/api/sdk/runtime-issue', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,status,request_id: /^[a-f0-9]{32}$/.test(requestId) ? requestId : ''})}).catch(() => {})
  }
  window.fetch = async (...args) => {
    let url
    try { url = new URL(typeof args[0] === 'string' || args[0] instanceof URL ? args[0] : args[0]?.url, window.location.href) } catch { return original(...args) }
    const tracked = url.origin === window.location.origin && url.pathname.startsWith('/api/') && !url.pathname.startsWith('/api/sdk/debug/') && !['/api/sdk/runtime-issue','/api/sdk/page-evidence','/api/sdk/session'].includes(url.pathname)
    if (!tracked) return original(...args)
    let response
    try { response = await original(...args) } catch (error) {
      if (error?.name === 'AbortError') throw error
      report('connection_failed', url.pathname)
      throw new Error(friendly)
    }
    if (!response.ok) {
      report('request_failed', url.pathname, response.status, response.status >= 500, response.headers?.get('X-Calabash-Request-Id') || '')
      const message = response.status >= 500 ? friendly : en ? 'Please check your entries or selected files and try again.' : '请检查填写的内容或所选文件后重试'
      throw new Error(message)
    }
    return response
  }
  const evidenceSent = new Set()
  function pageEvidence(code, event) {
    const item = {code}
    if (event) {
      try {
        const source = new URL(event.filename || event.target?.src || event.target?.href || '', window.location.href)
        const offset = source.pathname.lastIndexOf('/frontend/')
        if (source.origin === window.location.origin && offset >= 0) item.file = source.pathname.slice(offset + 1)
      } catch {}
      if (Number.isSafeInteger(event.lineno) && event.lineno > 0) item.line = event.lineno
      if (Number.isSafeInteger(event.colno) && event.colno > 0) item.column = event.colno
    }
    const key = JSON.stringify(item)
    if (evidenceSent.has(key) || evidenceSent.size >= 20) return
    evidenceSent.add(key)
    // No message, stack, element text, input, URL query or response body.
    void original('/api/sdk/page-evidence', {method:'POST',headers:{'Content-Type':'application/json'},body:key}).catch(() => {})
  }
  window.addEventListener('error', event => {
    report('javascript_error')
    pageEvidence(event.target?.src || event.target?.href ? 'PAGE_RESOURCE' : 'PAGE_SCRIPT', event)
  }, true)
  window.addEventListener('unhandledrejection', event => {
    if (event.reason?.name !== 'AbortError') { report('unhandled_rejection'); pageEvidence('PAGE_SCRIPT') }
  })
  if (typeof document !== 'undefined' && typeof MutationObserver !== 'undefined') {
    let ready = false
    const inspect = () => {
      const root = document.getElementById('app')
      if (ready || !root || !root.getClientRects().length || !root.children.length && !root.textContent.trim()) return
      ready = true; pageEvidence('PAGE_READY'); observer.disconnect(); clearTimeout(timer)
    }
    const observer = new MutationObserver(inspect)
    observer.observe(document.documentElement, {childList:true,subtree:true})
    const timer = setTimeout(() => { inspect(); if (!ready) { pageEvidence('PAGE_EMPTY'); observer.disconnect() } }, 10000)
    inspect()
  }
})()
