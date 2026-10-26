import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../component/tool_activity.js', import.meta.url), 'utf8');
const listeners = {};
let answer = false;
const root = {
  location: { origin: 'http://127.0.0.1:12345' },
  document: {
    documentElement: { lang: 'en' },
    addEventListener(name, callback) { listeners[name] = callback; },
  },
  addEventListener(name, callback) { listeners[name] = callback; },
  confirm() { return answer; },
};
root.top = root;
vm.runInNewContext(source, { window: root, location: root.location });
assert.equal(root.calabashToolRuns.allowLeave(), true);
root.calabashToolRuns.setBusy(true);
assert.equal(root.calabashToolRuns.allowLeave(), false);
let prevented = false;
listeners.click({
  target: { closest: () => ({ tagName: 'BUTTON' }) },
  preventDefault() { prevented = true; },
  stopImmediatePropagation() {},
});
assert.equal(prevented, true);
answer = true;
assert.equal(root.calabashToolRuns.allowLeave(), true);
const unloading = { preventDefault() { this.prevented = true; } };
listeners.beforeunload(unloading);
assert.equal(unloading.prevented, true);
const child = { top: root };
vm.runInNewContext(source, { window: child, location: root.location });
assert.equal(child.calabashToolRuns, root.calabashToolRuns);
root.calabashToolRuns.setBusy(false);
assert.equal(root.calabashToolRuns.allowLeave(), true);
console.log('Tool navigation guard checks passed');
