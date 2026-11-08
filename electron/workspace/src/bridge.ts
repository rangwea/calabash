/** One private Python owner per Host, with correlated bounded stdio messages. */
import { spawn, type ChildProcess } from 'node:child_process'
import { ProcessSupervisor } from './process-supervisor.ts'
import { randomUUID } from 'node:crypto'
export class PythonBridge {
  private child: ChildProcess | undefined
  private buffer = ''
  private pending = new Map<string, { resolve: (value: unknown) => void; reject: (error: Error) => void; timer?: ReturnType<typeof setTimeout> }>()
  private ending = false
  private supervisor = new ProcessSupervisor()
  private cleanup: Promise<void> | undefined
  private start(): ChildProcess {
    if (this.ending) throw new Error('Calabash is closing')
    if (this.child) return this.child
    const cwd = process.env.CALABASH_REPOSITORY
    const python = process.env.CALABASH_PYTHON
    if (!cwd || !python) throw new Error('Calabash tool runtime is unavailable')
    const child = spawn(python, ['-m', 'backend.harness_bridge'], { cwd, env: { ...process.env, PYTHONUNBUFFERED: '1', CALABASH_HARNESS_EMBEDDED: '1', CALABASH_PROCESS_CHANNEL: '3' }, stdio: ['pipe','pipe','pipe','pipe'], detached: true, windowsHide: true })
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
      if (Buffer.byteLength(this.buffer) > 8 * 1024 * 1024) { this.fail(); child.stdin!.end(); return }
      let end: number
      while ((end = this.buffer.indexOf('\n')) !== -1) {
        const line = this.buffer.slice(0, end); this.buffer = this.buffer.slice(end + 1)
        try {
          const response = JSON.parse(line) as { id: string; result?: unknown; error?: { message: string } }
          const request = this.pending.get(response.id)
          if (!request) continue
          this.pending.delete(response.id); clearTimeout(request.timer)
          if (response.error) request.reject(new Error(response.error.message)); else request.resolve(response.result)
        } catch { this.fail(); child.stdin!.end() }
      }
    })
    // Python writes full evidence to its local logs. Never forward it to the renderer/model.
    child.stderr!.resume()
    child.once('error', () => this.fail())
    child.once('exit', () => { this.fail(); this.child = undefined; this.ending = true; this.buffer = ''; this.cleanup = this.supervisor.drain() })
    return child
  }
  private fail(): void {
    for (const request of this.pending.values()) { clearTimeout(request.timer); request.reject(new Error('Calabash tool runtime disconnected. Please retry.')) }
    this.pending.clear()
  }
  get started(): boolean { return this.child !== undefined }
  async call(method: string, params: object): Promise<unknown> {
    const child = this.start()
    if (this.pending.size >= 32) return Promise.reject(new Error('Calabash is busy. Please retry.'))
    const id = randomUUID()
    const message = JSON.stringify({ id, method, params }) + '\n'
    if (Buffer.byteLength(message) > 2 * 1024 * 1024) return Promise.reject(new Error('Source request is too large'))
    return new Promise((resolve, reject) => {
      // Host task identities retain late results; an observer timeout must not cancel or replay an operation.
      this.pending.set(id, { resolve, reject })
      child.stdin!.write(message, error => { if (error) this.fail() })
    })
  }
  async stop(): Promise<void> {
    const child = this.child
    if (!child) { this.ending = true; await this.cleanup; return }
    try { while (await this.call('app.prepare_exit', {}) !== true) await new Promise(resolve => setTimeout(resolve, 250)) }
    finally {
      this.ending = true
      if (child.exitCode === null && child.signalCode === null) await new Promise<void>(resolve => { child.once('exit', () => resolve()); child.stdin!.end() }); await this.cleanup
    }
  }
}
