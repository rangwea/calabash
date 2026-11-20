import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { join } from 'node:path'
/** Private lifecycle channel from the trusted Python executor, never tool stdout. */
export interface OwnedProcess { pid: number; group: boolean; role: 'build' | 'preview' | 'tool'; ready?: boolean; control?: { port: number; token: string; hostToken: string } }
export class ProcessSupervisor {
  private identities = new Map<number, Promise<string | undefined>>()
  private async identity(pid: number): Promise<string | undefined> {
    if (process.platform === 'win32') {
      const shell = join(process.env.SystemRoot ?? 'C:\\Windows','System32','WindowsPowerShell','v1.0','powershell.exe')
      // Fixed OS identity query; only a validated numeric PID is interpolated. Never a tool/Agent command.
      const query = `[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); $p=Get-CimInstance Win32_Process -Filter 'ProcessId = ${pid}'; if($p){[Console]::Write($p.CreationDate.ToUniversalTime().ToString('o')+'|'+$p.ExecutablePath+'|'+$p.CommandLine)}`
      try { const result = await promisify(execFile)(shell,['-NoProfile','-NonInteractive','-Command',query],{timeout:5000,maxBuffer:65536,windowsHide:true}); return result.stdout.trim() || undefined } catch { return undefined }
    }
    try { const result = await promisify(execFile)('/bin/ps', ['-p',String(pid),'-o','lstart=','-o','command='], { timeout:2000, maxBuffer:65536 }); return result.stdout.trim() || undefined } catch { return undefined }
  }
  private owned = new Map<number, OwnedProcess>()
  receive(input: unknown) {
    if (!input || typeof input !== 'object') throw new Error('Invalid lifecycle packet')
    const value = input as OwnedProcess & { kind: string }
    if (!Number.isSafeInteger(value.pid) || value.pid < 2 || value.pid === process.pid) throw new Error('Invalid owned process')
    if (value.kind === 'start') {
      if (!['build','preview','tool'].includes(value.role) || typeof value.group !== 'boolean') throw new Error('Invalid process role')
      this.owned.set(value.pid, { pid: value.pid, group:value.group, role:value.role }); this.identities.set(value.pid,this.identity(value.pid))
    } else if (value.kind === 'stop') { this.owned.delete(value.pid); this.identities.delete(value.pid) }
    else {
      const entry = this.owned.get(value.pid)
      if (!entry) throw new Error('Unknown owned process')
      if (value.kind === 'ready') entry.ready = true
      else if (value.kind === 'control' && value.control && Number.isInteger(value.control.port) && value.control.port > 0 && value.control.port < 65536 && typeof value.control.token === 'string' && typeof value.control.hostToken === 'string') entry.control = value.control
      else throw new Error('Invalid lifecycle packet')
    }
  }
  get busy() { return this.owned.size > 0 }
  private alive(pid: number) { try { process.kill(pid,0); return true } catch (error) { return (error as NodeJS.ErrnoException).code !== 'ESRCH' } }
  private async signal(entry: OwnedProcess, force = false) {
    if (process.platform === 'win32') {
      const taskkill = join(process.env.SystemRoot ?? 'C:\\Windows','System32','taskkill.exe')
      try { await promisify(execFile)(taskkill,['/PID',String(entry.pid),'/T','/F'],{timeout:5000,windowsHide:true}) } catch { if (this.alive(entry.pid)) throw new Error('Owned process could not be stopped') }
      return
    }
    try { process.kill(entry.group ? -entry.pid : entry.pid, force ? 'SIGKILL' : 'SIGTERM') } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error }
  }
  async drain() {
    for (const entry of this.owned.values()) {
      const expected = await this.identities.get(entry.pid)
      // A PID alone is not an ownership proof after a crash; never signal a reused process.
      if (!expected || await this.identity(entry.pid) !== expected) { this.owned.delete(entry.pid); this.identities.delete(entry.pid); continue }
      // After executor failure, a reachable tool must acknowledge safe stop before
      // termination. Draining accepted work stays unbounded, so this waits on the
      // acknowledgement rather than on an arbitrary deadline; only an unreachable
      // executor bounds the loop (below), where no acknowledgement can ever arrive.
      if (entry.role === 'tool' && entry.ready && entry.control) {
        let unreachable = 0
        while (this.alive(entry.pid)) {
          try {
            const response = await fetch(`http://127.0.0.1:${entry.control.port}/api/sdk/prepare-exit`, { method:'POST', headers:{ Authorization:'Bearer '+entry.control.token, 'X-Calabash-Host':entry.control.hostToken }, signal:AbortSignal.timeout(2500) })
            const state = await response.json() as { running?: boolean }
            if (response.ok && state.running === false) break
            unreachable = 0
          } catch { /* Unknown state is not permission to interrupt a possible writer. */
            if (++unreachable >= 6) break
          }
          await new Promise(resolve => setTimeout(resolve,500))
        }
      }
      if (await this.identity(entry.pid) !== expected) { this.owned.delete(entry.pid); this.identities.delete(entry.pid); continue }
      await this.signal(entry)
      const deadline = Date.now()+5000
      while (this.alive(entry.pid) && Date.now()<deadline) await new Promise(resolve => setTimeout(resolve,50))
      if (await this.identity(entry.pid) === expected) await this.signal(entry,true); this.owned.delete(entry.pid); this.identities.delete(entry.pid)
    }
  }
}
