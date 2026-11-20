/** One private Python owner per Host, with correlated bounded stdio messages. */
import { spawn, type ChildProcess } from 'node:child_process'
import { ProcessSupervisor } from './process-supervisor.ts'
import { randomUUID } from 'node:crypto'
/** Query budget for a single host operation; slow builds and drains ask for more. */
const DEFAULT_TIMEOUT = 120_000
const MAX_RESPONSE = 8 * 1024 * 1024
const MAX_PENDING = 32
export class PythonBridge {
  private child: ChildProcess | undefined
  private buffer = ''
  private pending = new Map<string, { resolve: (value: unknown) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>()
  /** Set by stop() only: a crashed runtime must stay restartable. */
  private ending = false
  private supervisor = new ProcessSupervisor()
  private cleanup: Promise<void> | undefined
  private start(): ChildProcess {
    if (this.ending) throw new Error('Calabash is closing')
    if (this.child) return this.child
    const cwd = process.env.CALABASH_REPOSITORY
    const python = process.env.CALABASH_PYTHON
    if (!cwd || !python) throw new Error('Calabash tool runtime is unavailable')
    const child = spawn(python, process.env.CALABASH_PACKAGED_BACKEND === '1' ? [] : ['-m', 'backend.harness_bridge'], { cwd, env: { ...process.env, PYTHONUNBUFFERED: '1', CALABASH_HARNESS_EMBEDDED: '1', CALABASH_PROCESS_CHANNEL: '3' }, stdio: ['pipe','pipe','pipe','pipe'], detached: true, windowsHide: true })
    this.child = child
    let lifecycleBuffer = ''
    const lifecycle = child.stdio[3] as import('node:stream').Readable
    lifecycle.setEncoding('utf8')
    lifecycle.on('data', (chunk: string) => {
      lifecycleBuffer += chunk
      if (lifecycleBuffer.length > 65536) { this.fail(); return }
      let end: number
      while ((end = lifecycleBuffer.indexOf('\n')) !== -1) {
        const line = lifecycleBuffer.slice(0,end); lifecycleBuffer = lifecycleBuffer.slice(end+1)
        try { this.supervisor.receive(JSON.parse(line)) } catch { this.fail() }
      }
    })
    child.stdout!.setEncoding('utf8')
    child.stdout!.on('data', (chunk: string) => {
      this.buffer += chunk
      let end: number
      while ((end = this.buffer.indexOf('\n')) !== -1) {
        const line = this.buffer.slice(0, end); this.buffer = this.buffer.slice(end + 1)
        if (Buffer.byteLength(line) > MAX_RESPONSE) {
          // Refuse only the oversized answer; one large read must not take down every tool.
          const id = /"id"\s*:\s*"([^"]{1,80})"/.exec(line)?.[1]
          const request = id === undefined ? undefined : this.pending.get(id)
          if (request && id !== undefined) {
            this.pending.delete(id); clearTimeout(request.timer)
            request.reject(new Error('This result is too large to return. Open the file instead.'))
          }
          continue
        }
        try {
          const response = JSON.parse(line) as { id: string; result?: unknown; error?: { message: string } }
          const request = this.pending.get(response.id)
          if (!request) continue
          this.pending.delete(response.id); clearTimeout(request.timer)
          if (response.error) request.reject(new Error(response.error.message)); else request.resolve(response.result)
        } catch { this.fail(); child.stdin!.end(); return }
      }
      // An unterminated line beyond the cap can never become a valid response.
      if (Buffer.byteLength(this.buffer) > MAX_RESPONSE) { this.buffer = ''; this.fail() }
    })
    // Python writes full evidence to its local logs. Never forward it to the renderer/model.
    child.stderr!.resume()
    child.once('error', () => { if (this.child === child) this.fail() })
    child.once('exit', () => {
      // A previous child may exit after a restart; never let it clear the live one.
      if (this.child === child) { this.child = undefined; this.buffer = ''; this.cleanup = this.supervisor.drain() }
      this.fail()
    })
    return child
  }
  private fail(): void {
    for (const request of this.pending.values()) { clearTimeout(request.timer); request.reject(new Error('Calabash tool runtime disconnected. Please retry.')) }
    this.pending.clear()
  }
  get started(): boolean { return this.child !== undefined }
  /**
   * A settled promise is the caller's only contract: never leave one pending
   * forever. The Python operation itself keeps running, so a task identity the
   * host already returned can still be re-read after this rejects.
   */
  async call(method: string, params: object, timeoutMs = DEFAULT_TIMEOUT): Promise<unknown> {
    const child = this.start()
    if (this.pending.size >= MAX_PENDING) return Promise.reject(new Error('Calabash is busy. Please retry.'))
    const id = randomUUID()
    const message = JSON.stringify({ id, method, params }) + '\n'
    if (Buffer.byteLength(message) > 2 * 1024 * 1024) return Promise.reject(new Error('Source request is too large'))
    return new Promise((resolve, reject) => {
      // Host task identities retain late results; an observer timeout must not cancel or replay an operation.
      const timer = setTimeout(() => {
        if (!this.pending.delete(id)) return
        reject(new Error('Calabash did not finish this operation in time. Check the result before retrying.'))
      }, timeoutMs)
      timer.unref?.()
      this.pending.set(id, { resolve, reject, timer })
      child.stdin!.write(message, error => { if (error) this.fail() })
    })
  }
  async stop(): Promise<void> {
    const child = this.child
    this.ending = true
    if (!child) { await this.cleanup; return }
    // Draining accepted work is unbounded by design; waiting for the answer is not.
    const deadline = Date.now() + 30_000
    try {
      while (Date.now() < deadline) {
        try { if (await this.call('app.prepare_exit', {}, 5_000) === true) return } catch { /* retry until the deadline */ }
        await new Promise(resolve => setTimeout(resolve, 250))
      }
    } finally {
      if (child.exitCode === null && child.signalCode === null) await new Promise<void>(resolve => { const timer = setTimeout(resolve, 10_000); child.once('exit', () => { clearTimeout(timer); resolve() }); child.stdin!.end() })
      await this.cleanup
    }
  }
}
