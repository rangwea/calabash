/** Poll only the visible runtime. Late responses cannot change a new target. */
export function createConnectionMonitor(request, update, interval = 5000) {
  let version = 0, timer, controller
  function stop() {
    version++
    clearTimeout(timer)
    controller?.abort()
  }
  function start(resource, runtimeUrl) {
    stop()
    const ticket = version
    const origin = new URL(runtimeUrl).origin
    let failures = 0
    async function poll() {
      if (ticket !== version) return
      const current = new AbortController()
      controller = current
      const timeout = setTimeout(() => current.abort(), 3000)
      try {
        const value = await request(resource, {signal: current.signal})
        if (ticket !== version) return
        failures = 0
        update(value.origin && value.origin !== origin ? {state: 'unavailable', running: null} : value)
      } catch {
        if (ticket !== version) return
        if (++failures >= 2) update({state: 'unknown', running: null})
      } finally {
        clearTimeout(timeout)
        if (ticket === version) timer = setTimeout(poll, interval)
      }
    }
    void poll()
  }
  return {start, stop}
}
