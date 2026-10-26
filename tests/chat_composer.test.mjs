import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../component/ai_chat.py', import.meta.url), 'utf8');
const script = source.match(/_COMPOSER_KEYDOWN_JS = """([\s\S]*?)"""/)[1];
let now = 100;
let sent = 0;
let prevented = 0;
const handler = vm.runInNewContext(`(${script})`, {
  performance: { now: () => now },
  emit: () => sent++,
});
const enter = (properties = {}, target = {}) => handler({
  shiftKey: false, repeat: false, isComposing: false, keyCode: 13,
  target, preventDefault: () => prevented++, ...properties,
});

enter({ isComposing: true });
enter({ keyCode: 229 });
enter({}, { calabashComposing: true });
enter({}, { calabashComposing: false, calabashCompositionEnded: 100 });
enter({ shiftKey: true });
enter({ repeat: true });
assert.equal(sent, 0, 'IME confirmation, newline and held Enter must not send');
assert.equal(prevented, 0, 'IME and newline behavior must remain native');
now = 200;
enter({}, { calabashComposing: false, calabashCompositionEnded: 100 });
enter();
assert.equal(sent, 2, 'a fresh Enter after confirmation or plain English input sends');
assert.equal(prevented, 2);
console.log('Chat composer IME checks passed');
