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

const html = readFileSync(new URL('../desktop-ui/index.html', import.meta.url), 'utf8');
assert.match(html, /class="window-frame" data-tauri-drag-region><\/div>/);
assert.ok(!html.includes('frame-brand'));
assert.ok(html.includes('<h1>Calabash</h1>'), 'centered startup branding is retained');
console.log('Context menu and startup frame checks passed');
