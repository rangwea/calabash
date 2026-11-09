/** Prepare the official DSH descriptor without starting Electron or touching a profile. */
import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve, join } from 'node:path'
import { prepareDevelopmentProject } from './development-project.ts'
import { resolveDesktopBuildTarget } from './desktop-build-paths.mjs'
import { DESKTOP_HOST_PROTOCOL_VERSION } from '../src/host-protocol.ts'

export function prepareCalabashProject() {
  const appRoot = resolve(import.meta.dirname, '..'), root = resolve(appRoot, '../..')
  const electron = createRequire(import.meta.url)('electron') as string
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
}
if (import.meta.main) prepareCalabashProject()
