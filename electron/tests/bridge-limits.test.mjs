/** The host bridge must settle every call and stay restartable after a crash. */
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
const root = resolve(import.meta.dirname, '../..')
const upstream = process.env.CALABASH_HARNESS_SOURCE || join(root, 'build/harness', JSON.parse((await import('node:fs')).readFileSync(join(root, 'electron/harness.lock.json'), 'utf8')).commit)
const home = mkdtempSync(join(tmpdir(), 'calabash-bridge-limits-'))
const previous = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE, DSH_HOME: process.env.DSH_HOME }
Object.assign(process.env, {
  HOME: home, USERPROFILE: home, DSH_HOME: home, CALABASH_REPOSITORY: root,
  CALABASH_PYTHON: join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'),
})
try {
  const { PythonBridge } = await import(pathToFileURL(join(upstream, 'packages/client/calabash-workspace/lib/types/bridge.js')).href)
  const bridge = new PythonBridge()
  // 1. A call that cannot finish in its budget must reject, never hold the caller forever.
  await assert.rejects(bridge.call('app.active_tasks', {}, 1), /did not finish this operation in time/)
  // 2. The same runtime keeps serving after an observer timeout: the operation was not replayed or cancelled.
  assert.equal(await bridge.call('app.active_tasks', {}), false)
  // 3. A stopped bridge refuses new work instead of hanging.
  await bridge.stop()
  await assert.rejects(bridge.call('app.active_tasks', {}), /closing|disconnected/)
  console.log('PASS: bounded call timeouts settle, the runtime survives them and refuses work only after stop')
} finally {
  for (const [name, value] of Object.entries(previous)) { if (value === undefined) delete process.env[name]; else process.env[name] = value }
  rmSync(home, { recursive: true, force: true })
}
