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
  const patch = join(upstream, 'calabash.patch.yml');
  await copyFile(join(root, 'electron/overlays/calabash.patch.yml'), patch);
  await replaceOnce(join(upstream, 'apps/desktop-host/src/index.ts'), 'patchFiles: [],', `patchFiles: [${JSON.stringify(patch)}],`);
  await replaceOnce(join(upstream, 'apps/desktop/src/main.ts'), 'const state = await readWelcomeState()', "const state = process.env.CALABASH_LOCAL_WORKSPACE === '1' ? { localePreference: null, loggedIn: false, hasApiKey: false } : await readWelcomeState()");
  await replaceOnce(join(upstream, 'apps/desktop/src/main.ts'), 'if (!enteredWorkspace && needsWelcome({ loggedIn: state.loggedIn, hasApiKey: state.hasApiKey }))', "if (process.env.CALABASH_LOCAL_WORKSPACE !== '1' && !enteredWorkspace && needsWelcome({ loggedIn: state.loggedIn, hasApiKey: state.hasApiKey }))");
  await replaceOnce(join(upstream, 'apps/desktop/src/main.ts'), "applicationName: 'DeepSeek Harness',", "applicationName: 'Calabash',");
}
