/** Persist only presentation identities. URLs/tokens/processes are never restored from disk. */
import { mkdirSync, lstatSync, readFileSync, writeFileSync, renameSync } from 'node:fs'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'
export interface WorkspaceView { tabs: { project: string; name: string }[]; active: string; collapsed: boolean; query: string }
const empty = (): WorkspaceView => ({ tabs: [], active: '', collapsed: false, query: '' })
export class WorkspaceState {
  private value = empty()
  private file: string | undefined
  constructor(home?: string) {
    if (!home) return
    mkdirSync(home, { recursive: true, mode: 0o700 }); this.file = join(home, 'workspace.json')
    try { if (lstatSync(this.file).isSymbolicLink()) throw new Error('Linked workspace state'); this.value = this.validate(JSON.parse(readFileSync(this.file, 'utf8'))) }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error }
  }
  private validate(input: unknown): WorkspaceView {
    if (!input || typeof input !== 'object') throw new Error('Invalid workspace')
    const v = input as WorkspaceView
    if (!Array.isArray(v.tabs) || v.tabs.length > 32 || typeof v.active !== 'string' || typeof v.collapsed !== 'boolean' || typeof v.query !== 'string' || v.query.length > 200) throw new Error('Invalid workspace')
    const ids = new Set<string>()
    const tabs = v.tabs.map(tab => {
      if (!tab || !/^[a-z0-9][a-z0-9_-]{0,79}$/.test(tab.project) || !/^[a-z0-9][a-z0-9_-]{0,79}$/.test(tab.name)) throw new Error('Invalid tool identity')
      const id = `${tab.project}/${tab.name}`; if (ids.has(id)) throw new Error('Duplicate tab'); ids.add(id)
      return { project: tab.project, name: tab.name }
    })
    return { tabs, active: ids.has(v.active) ? v.active : '', collapsed: v.collapsed, query: v.query }
  }
  read() { return this.value }
  write(input: unknown) {
    const value = this.validate(input)
    if (this.file) { const tmp = this.file + '.' + randomUUID(); writeFileSync(tmp, JSON.stringify(value), { mode: 0o600, flag: 'wx' }); renameSync(tmp, this.file) }
    this.value = value
  }
}
