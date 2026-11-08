import { test } from 'node:test';
import assert from 'node:assert/strict';
import { main, verifyCheckout } from '../scripts/harness.mjs';
import { readFile } from 'node:fs/promises';
test('rejects unknown actions before spawning or writing', async () => {
  await assert.rejects(main('shell'), /Usage/);
});
test('pins full upstream commit and package manager', async () => {
  const lock = JSON.parse(await readFile(new URL('../electron/harness.lock.json', import.meta.url)));
  assert.match(lock.commit, /^[a-f0-9]{40}$/);
  assert.match(lock.packageManager, /^pnpm@\d+\.\d+\.\d+$/);
  await assert.rejects(verifyCheckout(process.cwd(), lock), /does not match/);
});
test('launcher omits automatic signing and public debug ports', async () => {
  const source = await readFile(new URL('../electron/launch.ts', import.meta.url), 'utf8');
  assert.ok(!source.includes('prepareDevelopmentApp'));
  assert.ok(!source.includes('--remote-debugging-port'));
  assert.ok(source.includes('harness-development'));
});
test('upstream edits are bounded, idempotent and fail closed on drift', async () => {
  const { replaceOnce } = await import('../electron/apply-overlay.mjs');
  const { mkdtemp, writeFile, rm } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const directory = await mkdtemp(join(tmpdir(), 'calabash-overlay-'));
  try {
    const file = join(directory, 'source.ts');
    await writeFile(file, 'before');
    await replaceOnce(file, 'before', 'after');
    await replaceOnce(file, 'before', 'after');
    assert.equal(await readFile(file, 'utf8'), 'after');
    await writeFile(file, 'changed upstream');
    await assert.rejects(replaceOnce(file, 'before', 'after'), /integration point changed/);
  } finally { await rm(directory, { recursive: true }); }
});
