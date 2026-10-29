import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../component/native_file_drop.js', import.meta.url), 'utf8');
const calls = [];
const events = [];
const local = new Map();
const native = new Map();
const window = {path_prefix: '', addEventListener: (key, value) => native.set(key, value), removeEventListener: key => native.delete(key)};
const definition = vm.runInNewContext('(' + source.replace('export default', '').trim().replace(/;$/, '') + ')', {
  window, FormData, File, Blob,
  fetch: async (url, options) => { calls.push({url, options}); return {ok: true}; },
});
const classes = new Set();
const instance = {$el: {isConnected: true, getClientRects: () => [1], dataset: {},
  classList: {add: key => classes.add(key), remove: key => classes.delete(key), toggle: (key, value) => value ? classes.add(key) : classes.delete(key)},
  addEventListener: (key, callback) => local.set(key, callback), removeEventListener: key => local.delete(key)},
  imageUploadUrl: '/_nicegui/client/synthetic/upload/1', $emit: (...args) => events.push(args)};
Object.assign(instance, definition.methods);
definition.mounted.call(instance);
const one = new File(['one'], 'one.png', {type: 'image/png'});
const two = new File(['two'], 'two.png', {type: 'image/png'});
await instance.uploadImages([one, two]);
assert.equal(calls.length, 1);
assert.equal([...calls[0].options.body.entries()].length, 2, 'multipart field names must preserve both images');
assert.equal(instance.$el.dataset.uploading, 'true', 'do not allow send before server finishes registering images');
await instance.uploadImages([one]);
assert.equal(events.at(-1)[1].error, 'upload_busy');
instance.uploadDone();
assert.equal(instance.$el.dataset.uploading, undefined);
let prevented = false;
local.get('paste')({clipboardData: {items: [{kind: 'string', type: 'text/plain'}]}, preventDefault: () => prevented = true});
assert.equal(prevented, false, 'ordinary text paste remains native');
local.get('paste')({clipboardData: {items: [{kind: 'file', type: 'image/png', getAsFile: () => one}]}, preventDefault: () => prevented = true});
assert.equal(prevented, true);
await Promise.resolve();
assert.equal(calls.length, 2);
instance.uploadDone();
local.get('drop')({dataTransfer: {files: [one]}, preventDefault: () => {}});
await Promise.resolve();
assert.equal(calls.length, 3, 'browser drop uploads image bytes');
instance.uploadDone();
window.__TAURI_INTERNALS__ = {};
local.get('drop')({dataTransfer: {files: [one]}, preventDefault: () => {}});
assert.equal(calls.length, 3, 'native Tauri drop must not also upload through DOM');
native.get('calabash-native-files')({detail: {ticket: 'native-ticket'}});
assert.equal(events.at(-1)[1].ticket, 'native-ticket');
await instance.uploadImages(Array(6).fill(one));
assert.equal(events.at(-1)[1].error, 'image_count');
instance.$el.getClientRects = () => [];
const count = events.length;
native.get('calabash-native-files')({detail: {ticket: 'hidden-chat'}});
assert.equal(events.length, count, 'hidden chats cannot receive image drops');
definition.beforeUnmount.call(instance);
assert.equal(native.size, 0);
assert.equal(local.size, 0);
console.log('Image paste/drop, multipart, busy-state and native deduplication checks passed');
