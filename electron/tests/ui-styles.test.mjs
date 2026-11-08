/** Test the shipping DSH source/codec and mention parser without a browser or model. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const lock = JSON.parse(await readFile(join(root, 'electron/harness.lock.json')));
const upstream = resolve(process.env.CALABASH_HARNESS_SOURCE ?? join(root, 'build/harness', lock.commit));
const base = join(upstream, 'packages/client/calabash-workspace/lib/types');
const { requestedStyle } = await import(pathToFileURL(join(base, 'style-selection.js')));
for (const [text, expected] of [['@ui:soft Create', 'soft'], ['@柔和彩色 创建', 'soft'], ['@Office do it @Compact， please', 'compact'], ['user@Office hello', null], ['@ui:unknown create', null], ['@Softly create', null], ['@SOFT\ncreate', 'soft'], ['Fix without changing style', null]]) {
  assert.equal(requestedStyle(text), expected, text);
}
const { registerUIStyles } = await import(pathToFileURL(join(base, 'client/ui-styles.js')));
const presets = [];
for (const id of ['office', 'compact', 'soft']) presets.push(JSON.parse(await readFile(join(root, 'agent/skills/calabash/references/ui-presets', id, 'preset.json'))));
const english = JSON.parse(await readFile(join(root, 'core/locales/en.json')));
for (const preset of presets) { preset.title_en = english[preset.title]; preset.description_en = english[preset.description]; }
let source, language = 'zh';
const ctx = { locale: { getSnapshot: () => ({ active: language }) }, effect: factory => factory(), inputTriggers: { registerSource: value => { source = value; return () => {}; } } };
registerUIStyles(ctx, async () => presets);
const request = query => ({ query, quoted: false, drilled: false, signal: new AbortController().signal });
let menu = await source.candidates({}, request('ui:'));
assert.equal(menu.length, 3);
assert.equal((await source.candidates({}, request('ui'))).length, 3);
assert.equal((await source.candidates({}, request('样式'))).length, 3);
assert.ok(menu.some(value => value.label === '柔和彩色'));
const pick = source.onPick({ candidate: menu.find(value => value.value === 'soft') });
assert.equal(pick.insert.ref, '@ui:soft');
assert.equal(pick.insert.clipboardText, '@ui:soft');
assert.equal(await source.codec.serialize(pick.insert.ref, new AbortController().signal), '@ui:soft');
assert.equal(await source.codec.serialize('@柔和彩色', new AbortController().signal), '@ui:soft');
await assert.rejects(source.codec.serialize('@ui:unknown', new AbortController().signal), /unavailable/);
assert.equal((await source.candidates({}, request('Compact')))[0].value, 'compact');
assert.equal((await source.candidates({}, { ...request(''), quoted: true })).length, 0);
const aborted = new AbortController(); aborted.abort();
assert.deepEqual(await source.candidates({}, { ...request(''), signal: aborted.signal }), []);
language = 'en'; menu = await source.candidates({}, request('Soft'));
assert.equal(menu[0].label, 'Soft'); assert.equal(menu[0].description, english[presets.find(p => p.id === 'soft').description]);
console.log('PASS: shipping @style source filters, localizes, inserts, copies, restores and serializes canonical style references');
