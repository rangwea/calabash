/** Host-owned bounded task journal. Never persist request/source/result payloads. */
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, renameSync, writeFileSync, lstatSync } from 'node:fs'
import { join } from 'node:path'
export interface HostTask { id: string; operation: string; state: 'queued' | 'running' | 'succeeded' | 'failed' | 'interrupted'; phase: string; created: number; updated: number }
interface Entry { view: HostTask; digest: string; key: string; scope: string; resource: string; execute?: () => Promise<unknown>; promise: Promise<unknown>; resolve: (value: unknown) => void; reject: (error: Error) => void; result?: unknown }
export class HostTasks {
  private entries = new Map<string, Entry>()
  private keys = new Map<string, string>()
  private active = new Set<string>()
  private running = 0
  private ending = false
  private file: string | undefined
  private timer: ReturnType<typeof setTimeout> | undefined
  private dirty = false
  constructor(home?: string, private limit = 2) {
    if (!home) return
    mkdirSync(home, { recursive: true, mode: 0o700 }); this.file = join(home, 'tasks.json')
    try {
      if (lstatSync(this.file).isSymbolicLink()) throw new Error('Linked task journal')
      const saved = JSON.parse(readFileSync(this.file, 'utf8')) as HostTask[]
      for (const view of saved.slice(-128)) {
        if (view.state === 'queued' || view.state === 'running') { view.state = 'interrupted'; view.phase = 'interrupted' }
        this.entries.set(view.id, { view, key: '', scope: '', resource: '', digest: '', promise: Promise.resolve(undefined), resolve() {}, reject() {} })
      }
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error }
  }
  /** State changes are frequent and synchronous; coalesce them off the hot path. */
  private save(immediate = false) {
    if (!this.file) return
    if (immediate) { if (this.timer) { clearTimeout(this.timer); this.timer = undefined } this.write(); return }
    this.dirty = true
    if (this.timer) return
    this.timer = setTimeout(() => { this.timer = undefined; this.write() }, 250)
    this.timer.unref?.()
  }
  private write() {
    if (!this.file || !this.dirty) return
    this.dirty = false
    const temporary = this.file + '.' + randomUUID()
    writeFileSync(temporary, JSON.stringify([...this.entries.values()].map(entry => entry.view).slice(-128)), { mode: 0o600, flag: 'wx' }); renameSync(temporary, this.file)
  }
  submit(operation: string, input: object, resource: string, key: string, execute: () => Promise<unknown>, scope = ''): string {
    const digest = createHash('sha256').update(JSON.stringify([operation, input])).digest('hex')
    const previous = this.entries.get(this.keys.get(key) ?? '')
    if (previous) { if (previous.digest !== digest) throw new Error('Operation identity reused with changed input'); return previous.view.id }
    if (this.ending || [...this.entries.values()].filter(entry => entry.execute).length >= 32) throw new Error('Host is busy or closing')
    // Finished results are kept for reconnect/requery; bounded retention never evicts an active task.
    for (const [id, entry] of this.entries) if (this.entries.size >= 128 && !entry.execute) { this.entries.delete(id); if (entry.key) this.keys.delete(entry.key) }
    let resolve!: Entry['resolve'], reject!: Entry['reject']
    const promise = new Promise<unknown>((yes, no) => { resolve = yes; reject = no }); void promise.catch(() => {})
    const id = randomUUID(), now = Date.now()
    this.entries.set(id, { view: { id, operation, state: 'queued', phase: 'queued', created: now, updated: now }, digest, scope, resource, key, execute, promise, resolve, reject }); this.keys.set(key, id)
    this.save(true); this.pump(); return id
  }
  private pump() {
    for (const entry of this.entries.values()) {
      if (this.running >= this.limit) return
      if (entry.view.state !== 'queued' || !entry.execute || this.active.has(entry.resource)) continue
      this.running++; this.active.add(entry.resource); entry.view.state = 'running'; entry.view.phase = 'working'; entry.view.updated = Date.now(); this.save()
      void entry.execute().then(value => { entry.result = value; entry.view.state = 'succeeded'; entry.resolve(value) }, () => { entry.view.state = 'failed'; entry.reject(new Error('Unable to complete. Check the current state before retrying.')) }).finally(() => {
        delete entry.execute; entry.view.phase = entry.view.state; entry.view.updated = Date.now(); this.running--; this.active.delete(entry.resource); this.save(); this.pump()
      })
    }
  }
  /** A task answer belongs to the caller that started it; never quote another scope. */
  inspect(id: string, scope = '') {
    const entry = this.entries.get(id)
    if (!entry || (entry.scope && entry.scope !== scope)) throw new Error('Task unavailable')
    return { ...entry.view, resultAvailable: entry.result !== undefined, ...(entry.view.state === 'succeeded' && entry.result !== undefined ? { result: entry.result } : {}) }
  }
  wait(id: string) { const entry = this.entries.get(id); if (!entry) throw new Error('Task unavailable'); return entry.promise }
  list() { return [...this.entries.values()].map(entry => ({ ...entry.view })) }
  get busy() { return [...this.entries.values()].some(entry => entry.execute) }
  async drain() { this.ending = true; await Promise.allSettled([...this.entries.values()].filter(entry => entry.execute).map(entry => entry.promise)); this.save(true) }
}
