import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../component/context_menu.js', import.meta.url), 'utf8');
const document = new EventTarget();
const context = vm.createContext({ window: {}, document });
vm.runInContext(source, context);
vm.runInContext(source, context);
let customMenuOpened = 0;
document.addEventListener('contextmenu', () => customMenuOpened++);
const event = new Event('contextmenu', { bubbles: true, cancelable: true });
document.dispatchEvent(event);
assert.equal(event.defaultPrevented, true, 'native context menu is disabled');
assert.equal(customMenuOpened, 1, 'custom context menu handlers remain enabled');
const click = new Event('click', { cancelable: true });
document.dispatchEvent(click);
assert.equal(click.defaultPrevented, false, 'ordinary clicks are unchanged');

const ui = readFileSync(new URL('../desktop-ui/src/App.vue', import.meta.url), 'utf8');
assert.match(ui, /class="titlebar" data-tauri-drag-region/);
assert.ok(ui.includes('<h1>Calabash</h1>'));
console.log('Context menu and Vue window frame checks passed');
