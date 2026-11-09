import { readFile, writeFile, copyFile, cp } from 'node:fs/promises';
import { join } from 'node:path';
/** Fail closed when the pinned upstream integration point changes. */
export async function replaceOnce(file, before, after) {
  const source = await readFile(file, 'utf8');
  if (source.includes(after)) return;
  if (source.split(before).length !== 2) throw new Error(`Upstream integration point changed: ${file}`);
  await writeFile(file, source.replace(before, after));
}
export async function applyOverlay(root, upstream) {
  // Replace native assets as well as the in-page brand component.
  for (const name of ['icon.png', 'icon-macos.png', 'icon-windows.png']) {
    await copyFile(join(root, 'electron/icons/icon.png'), join(upstream, 'apps/desktop/resources', name));
  }
  const desktopMain = join(upstream, 'apps/desktop/src/main.ts');
  await replaceOnce(desktopMain, 'const window = new BrowserWindow({',
    "const window = new BrowserWindow({\n    icon: nativeImage.createFromPath(app.isPackaged ? join(process.resourcesPath, 'icon.png') : join(app.getAppPath(), 'resources', 'icon.png')),");
  await replaceOnce(desktopMain, 'app.setAboutPanelOptions({',
    "if (process.platform === 'darwin') app.dock?.setIcon(nativeImage.createFromPath(applicationIconPath))\n  app.setAboutPanelOptions({");
  await replaceOnce(join(upstream, 'apps/desktop/scripts/electron-builder-config.mjs'),
    "productName: 'DeepSeek Harness',", "productName: 'Calabash',");
  await cp(join(root, 'electron/workspace'), join(upstream, 'packages/client/calabash-workspace'), { recursive: true });
  const presetRoot = join(root, 'agent/skills/calabash/references/ui-presets');
  const { readdir } = await import('node:fs/promises');
  const presets = [];
  for (const entry of (await readdir(presetRoot, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
    if (entry.isDirectory()) presets.push(JSON.parse(await readFile(join(presetRoot, entry.name, 'preset.json'), 'utf8')));
  }
  await writeFile(join(upstream, 'packages/client/calabash-workspace/src/presets.ts'),
    `// Generated from Calabash's canonical preset manifests.\nimport type { UIPreset } from './types.ts'\nexport const presetCatalog: UIPreset[] = ${JSON.stringify(presets)}\n`);
  for (const face of ['host', 'client']) {
    const reference = `"references": [\n    { "path": "./packages/client/calabash-workspace/tsconfig.${face}.json" },`;
    await replaceOnce(join(upstream, `tsconfig.${face}.json`), '"references": [', reference);
  }
  await copyFile(join(root, 'electron/overlays/brand.ts'), join(upstream, 'packages/client/ui-brand-official/src/client/index.ts'));
  const importer = await readFile(join(root, 'electron/workspace/pnpm-importer.yaml'), 'utf8');
  const lockPath = join(upstream, 'pnpm-lock.yaml');
  const lock = await readFile(lockPath, 'utf8');
  if (lock.includes('  packages/client/calabash-workspace:\n')) {
    const updated = lock.replace(/^  packages\/client\/calabash-workspace:\n[\s\S]*?(?=^  [^ ]|^packages:)/m, importer);
    if (updated === lock && !lock.includes(importer.trimEnd())) throw new Error('Calabash lock importer changed unexpectedly');
    await writeFile(lockPath, updated);
  } else await replaceOnce(lockPath, 'importers:\n', 'importers:\n' + importer);
  await replaceOnce(join(upstream, 'apps/desktop-host/src/quit-inspection.ts'), 'const activeTasks = hasDesktopActiveTasks(liveAgents, jobs)', "const activeTasks = hasDesktopActiveTasks(liveAgents, jobs) || await (ctx.get('calabashWorkspace') as { activeTasks(): Promise<boolean> } | undefined)?.activeTasks() === true");
  await replaceOnce(join(upstream, 'packages/boot/app-boot/src/index.ts'), "const requiredStartupEntryIds = new Set<string>([", "const requiredStartupEntryIds = new Set<string>([\n  'calabash-workspace',");
  // Calabash supplies defaults, not a launcher veto over explicit user choices.
  const profileContext = join(upstream, 'packages/boot/app-boot/src/profile-context.ts');
  await replaceOnce(profileContext,
    '...readBundlePatches(binName, context, initialProfile),',
    "...readBundlePatches(binName, context, initialProfile),\n    ...(process.env.CALABASH_LOCAL_WORKSPACE === '1' ? context.overlays : []),");
  await replaceOnce(profileContext, '...context.overlays,',
    "...(process.env.CALABASH_LOCAL_WORKSPACE === '1' ? [] : context.overlays),");
  const patch = join(upstream, 'calabash.patch.yml');
  await copyFile(join(root, 'electron/overlays/calabash.patch.yml'), patch);
  const hostMain = join(upstream, 'apps/desktop-host/src/index.ts');
  const hostSource = await readFile(hostMain, 'utf8');
  await replaceOnce(hostMain, hostSource.includes('patchFiles: [],') ? 'patchFiles: [],' : `patchFiles: [${JSON.stringify(patch)}],`, "patchFiles: [join(runtimeDir, 'calabash.patch.yml')],");
  await replaceOnce(desktopMain, 'async function main(): Promise<void> {',
    `async function main(): Promise<void> {
  if (app.isPackaged) {
    process.env.CALABASH_LOCAL_WORKSPACE = '1'
    process.env.DSH_HOME = process.env.CALABASH_HARNESS_HOME ?? join(app.getPath('home'), '.calabash', 'harness')
    process.env.CALABASH_REPOSITORY = join(process.resourcesPath, 'calabash', 'backend')
    process.env.CALABASH_PYTHON = join(process.env.CALABASH_REPOSITORY, process.platform === 'win32' ? 'calabash-backend.exe' : 'calabash-backend')
    process.env.CALABASH_PACKAGED_BACKEND = '1'
    process.env.CALABASH_FRONTEND_RUNTIME = join(process.resourcesPath, 'calabash', 'frontend-runtime')
  }`);
  await replaceOnce(desktopMain, 'resolveDesktopPolicyConfig(policyInput, !app.isPackaged)',
    "resolveDesktopPolicyConfig(policyInput, !app.isPackaged || process.env.CALABASH_LOCAL_WORKSPACE === '1')");
  await replaceOnce(desktopMain, 'const automaticCheck = (): void => {',
    "const automaticCheck = (): void => {\n    if (process.env.CALABASH_LOCAL_WORKSPACE === '1') return");
  await replaceOnce(join(upstream, 'apps/desktop/src/main.ts'), 'const state = await readWelcomeState()', "const state = process.env.CALABASH_LOCAL_WORKSPACE === '1' ? { localePreference: null, loggedIn: false, hasApiKey: false } : await readWelcomeState()");
  await replaceOnce(join(upstream, 'apps/desktop/src/main.ts'), 'if (!enteredWorkspace && needsWelcome({ loggedIn: state.loggedIn, hasApiKey: state.hasApiKey }))', "if (process.env.CALABASH_LOCAL_WORKSPACE !== '1' && !enteredWorkspace && needsWelcome({ loggedIn: state.loggedIn, hasApiKey: state.hasApiKey }))");
  await replaceOnce(join(upstream, 'apps/desktop/src/main.ts'), "applicationName: 'DeepSeek Harness',", "applicationName: 'Calabash',");
}
