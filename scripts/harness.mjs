/** Pinned official Electron workspace; generated upstream code stays out of source control. */
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { readFile, mkdir, access, writeFile, copyFile, readdir } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve, join, dirname } from 'node:path';
import { applyOverlay } from '../electron/apply-overlay.mjs';

export const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export async function run(command, args, cwd, env = process.env) {
  return new Promise((accept, reject) => {
    const child = spawn(command, args, { cwd, env, stdio: 'inherit', shell: false });
    const forward = signal => child.kill(signal);
    const interrupt = () => forward('SIGINT');
    const terminate = () => forward('SIGTERM');
    process.on('SIGINT', interrupt); process.on('SIGTERM', terminate);
    const clean = () => { process.off('SIGINT', interrupt); process.off('SIGTERM', terminate); };
    child.once('error', error => { clean(); reject(error); });
    child.once('exit', (code, signal) => { clean(); code === 0 ? accept() : reject(new Error(`${command} exited (${signal ?? code})`)); });
  });
}
export async function verifyCheckout(directory, lock) {
  const { execFile } = await import('node:child_process');
  const { promisify } = await import('node:util');
  const git = promisify(execFile);
  const { stdout } = await git('git', ['rev-parse', 'HEAD'], { cwd: directory });
  if (stdout.trim() !== lock.commit) throw new Error('Harness checkout does not match electron/harness.lock.json');
  const manifest = JSON.parse(await readFile(join(directory, 'package.json'), 'utf8'));
  if (manifest.version !== lock.version || manifest.packageManager !== lock.packageManager) throw new Error('Harness release metadata differs from the pinned release');
}
export async function overlayFingerprint(root = repositoryRoot) {
  const digest = createHash('sha256');
  async function visit(directory) {
    for (const item of (await readdir(directory, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      const path = join(directory, item.name);
      if (item.isDirectory()) await visit(path);
      else if (item.isFile()) { digest.update(path.slice(root.length)); digest.update(await readFile(path)); }
      else throw new Error('Overlay sources must not contain links');
    }
  }
  await visit(join(root, 'electron/workspace'));
  await visit(join(root, 'electron/overlays'));
  await visit(join(root, 'electron/icons'));
  await visit(join(root, 'agent/skills/calabash/references/ui-presets'));
  digest.update(await readFile(join(root, 'electron/apply-overlay.mjs')));
  return digest.digest('hex');
}
export async function main(action = process.argv[2]) {
  if (!['prepare', 'build', 'start'].includes(action)) throw new Error('Usage: node scripts/harness.mjs prepare|build|start');
  if (Number(process.versions.node.split('.')[0]) < 25 && !(Number(process.versions.node.split('.')[0]) === 24 && Number(process.versions.node.split('.')[1]) >= 9)) throw new Error('Harness requires Node >=24.9');
  const lock = JSON.parse(await readFile(join(repositoryRoot, 'electron/harness.lock.json'), 'utf8'));
  const upstream = resolve(process.env.CALABASH_HARNESS_SOURCE ?? join(repositoryRoot, 'build/harness', lock.commit));
  try { await access(join(upstream, '.git')); }
  catch {
    if (action !== 'prepare') throw new Error('Run npm run electron:prepare first');
    await mkdir(dirname(upstream), { recursive: true });
    await run('git', ['init', upstream], repositoryRoot);
    await run('git', ['fetch', '--depth=1', lock.repository, lock.commit], upstream);
    await run('git', ['checkout', '--detach', 'FETCH_HEAD'], upstream);
  }
  await verifyCheckout(upstream, lock);
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const runtimeEnvironment = { ...process.env, CALABASH_REPOSITORY: repositoryRoot };
  const pinnedPnpm = join(upstream, 'apps/desktop/node_modules/pnpm/bin/pnpm.cjs');
  const pnpm = async args => {
    let installed = true;
    try { await access(pinnedPnpm); } catch { installed = false; }
    if (installed) return run(process.execPath, [pinnedPnpm, ...args], upstream, runtimeEnvironment);
    if (action !== 'prepare') throw new Error('Run electron:prepare first');
    return process.env.npm_execpath
    ? run(process.execPath, [process.env.npm_execpath, 'exec', '--yes', `--package=${lock.packageManager}`, '--', 'pnpm', ...args], upstream, runtimeEnvironment)
    : run(npm, ['exec', '--yes', `--package=${lock.packageManager}`, '--', 'pnpm', ...args], upstream, runtimeEnvironment);
  };
  if (action === 'prepare') {
    await pnpm(['install', '--frozen-lockfile', '--ignore-scripts']);
    // Electron's official binary installer is the only dependency install script invoked here.
    await run(process.execPath, [join(upstream, 'apps/desktop/node_modules/electron/install.js')], upstream);
    return;
  }
  if (action === 'build') {
    await applyOverlay(repositoryRoot, upstream);
    // Keep every upstream version frozen; registry policy verification may fetch metadata.
    await pnpm(['install', '--ignore-scripts', '--frozen-lockfile']);
    await copyFile(join(repositoryRoot, 'electron/launch.ts'), join(upstream, 'apps/desktop/scripts/calabash-launch.ts'));
    await copyFile(join(repositoryRoot, 'electron/prepare-project.ts'), join(upstream, 'apps/desktop/scripts/calabash-prepare-project.ts'));
    await pnpm(['run', 'build:artifacts']);
    await pnpm(['--filter', '@deepseek-ai/dsh-desktop', 'run', 'prepare:primary-runtime']);
    await writeFile(join(upstream, '.calabash-build.json'), JSON.stringify({ commit: lock.commit, version: lock.version, overlay: await overlayFingerprint() }));
    return;
  }
  const built = JSON.parse(await readFile(join(upstream, '.calabash-build.json'), 'utf8').catch(() => { throw new Error('Run npm run electron:build first'); }));
  if (built.commit !== lock.commit || built.overlay !== await overlayFingerprint()) throw new Error('Rebuild the pinned Harness release');
  await copyFile(join(repositoryRoot, 'electron/launch.ts'), join(upstream, 'apps/desktop/scripts/calabash-launch.ts'));
    await copyFile(join(repositoryRoot, 'electron/prepare-project.ts'), join(upstream, 'apps/desktop/scripts/calabash-prepare-project.ts'));
  await pnpm(['exec', 'tsx', 'apps/desktop/scripts/calabash-launch.ts']);
}
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
