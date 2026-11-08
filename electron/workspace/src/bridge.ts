/** One private Python owner per Host, with correlated bounded stdio messages. */
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID } from 'node:crypto'
export class PythonBridge {
  private child: ChildProcessWithoutNullStreams | undefined
  private buffer = ''
  private pending = new Map<string, { resolve: (value: unknown) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>()
  private ending = false
  private start(): ChildProcessWithoutNullStreams {
    if (this.ending) throw new Error('Calabash is closing')
    if (this.child) return this.child
    const cwd = process.env.CALABASH_REPOSITORY
    const python = process.env.CALABASH_PYTHON
    if (!cwd || !python) throw new Error('Calabash tool runtime is unavailable')
    const child = spawn(python, ['-m', 'backend.harness_bridge'], { cwd, env: { ...process.env, PYTHONUNBUFFERED: '1', CALABASH_HARNESS_EMBEDDED: '1' }, stdio: 'pipe' })
    this.child = child
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => {
      this.buffer += chunk
      if (Buffer.byteLength(this.buffer) > 8 * 1024 * 1024) { this.fail(); child.stdin.end(); return }
      let end: number
      while ((end = this.buffer.indexOf('\n')) !== -1) {
        const line = this.buffer.slice(0, end); this.buffer = this.buffer.slice(end + 1)
        try {
          const response = JSON.parse(line) as { id: string; result?: unknown; error?: { message: string } }
          const request = this.pending.get(response.id)
          if (!request) continue
          this.pending.delete(response.id); clearTimeout(request.timer)
          if (response.error) request.reject(new Error(response.error.message)); else request.resolve(response.result)
        } catch { this.fail(); child.stdin.end() }
      }
    })
    // Python writes full evidence to its local logs. Never forward it to the renderer/model.
    child.stderr.resume()
    child.once('error', () => this.fail())
    child.once('exit', () => { this.fail(); this.child = undefined; this.buffer = '' })
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
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('Tool operation is taking longer than expected. Check its current state before retrying.')) }, 180000)
      this.pending.set(id, { resolve, reject, timer })
      child.stdin.write(message, error => { if (error) this.fail() })
    })
  }
  async stop(): Promise<void> {
    const child = this.child
    if (!child) { this.ending = true; return }
    try { while (await this.call('app.prepare_exit', {}) !== true) await new Promise(resolve => setTimeout(resolve, 250)) }
    finally {
      this.ending = true
      if (child.exitCode === null && child.signalCode === null) await new Promise<void>(resolve => { child.once('exit', () => resolve()); child.stdin.end() })
    }
  }
}
