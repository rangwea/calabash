/** Runs the official desktop entry without upstream's macOS development re-signing. */
import { createRequire } from 'node:module'
import { execFileSync, spawn } from 'node:child_process'
import { readFileSync, mkdirSync, existsSync, symlinkSync } from 'node:fs'
import { homedir } from 'node:os'
import { resolve, join } from 'node:path'
import { prepareDevelopmentProject } from './development-project.ts'
import { developmentRuntimeDirectory, resolveDesktopBuildTarget } from './desktop-build-paths.mjs'
import { DESKTOP_HOST_PROTOCOL_VERSION } from '../src/host-protocol.ts'
const appRoot = resolve(import.meta.dirname, '..')
const root = resolve(appRoot, '../..')
const require = createRequire(import.meta.url)
const electron = require('electron') as string
const home = resolve(process.env.CALABASH_HARNESS_HOME ?? join(homedir(), '.calabash', 'harness-development'))
mkdirSync(home, { recursive: true })
const version = JSON.parse(readFileSync(join(appRoot, 'package.json'), 'utf8')).version as string
const pnpmVersion = JSON.parse(readFileSync(join(appRoot, 'node_modules/pnpm/package.json'), 'utf8')).version as string
prepareDevelopmentProject({
  projectDir: join(appRoot, '.desktop-build/development/project'),
  cliDir: join(root, 'apps/cli'), hostDir: join(root, 'apps/desktop-host'),
  dependencyDir: join(root, 'node_modules/.pnpm/node_modules'),
  release: { schemaVersion: 1, version, hostProtocolVersion: DESKTOP_HOST_PROTOCOL_VERSION,
    nodeVersion: execFileSync(electron, ['-p', 'process.versions.node'], { encoding: 'utf8', env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' } }).trim(), pnpmVersion },
  target: resolveDesktopBuildTarget(),
})
const pluginLink = join(appRoot, '.desktop-build/development/project/node_modules/@calabash/harness-workspace')
mkdirSync(resolve(pluginLink, '..'), { recursive: true })
if (!existsSync(pluginLink)) symlinkSync(join(root, 'packages/client/calabash-workspace'), pluginLink, process.platform === 'win32' ? 'junction' : 'dir')
const profilePluginLink = join(home, 'profiles/desktop/node_modules/@calabash/harness-workspace')
mkdirSync(resolve(profilePluginLink, '..'), { recursive: true })
if (!existsSync(profilePluginLink)) symlinkSync(join(root, 'packages/client/calabash-workspace'), profilePluginLink, process.platform === 'win32' ? 'junction' : 'dir')
const repository = process.env.CALABASH_REPOSITORY
if (!repository) throw new Error('Calabash repository path is required')
const env = { ...process.env, CALABASH_PYTHON: process.env.CALABASH_PYTHON ?? join(repository, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'), DSH_HOME: home, CALABASH_LOCAL_WORKSPACE: '1',
  DSH_DESKTOP_PRIMARY_RUNTIME_DIR: developmentRuntimeDirectory(), DSH_DESKTOP_OPEN_DEVTOOLS: '0' }
delete env.ELECTRON_RUN_AS_NODE
const child = spawn(electron, [`--user-data-dir=${join(home, 'electron-user-data')}`, appRoot], { env, stdio: 'inherit' })
process.on('SIGINT', () => child.kill('SIGINT'))
process.on('SIGTERM', () => child.kill('SIGTERM'))
child.once('error', error => { console.error(error.message); process.exitCode = 1 })
child.once('exit', code => { process.exitCode = code ?? 1 })
