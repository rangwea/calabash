import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
const source = readFileSync(new URL('../scripts/tool_runtime_guard.js', import.meta.url),'utf8')
const events = [], records = [], handlers = new Map()
let abort = false
const win = {location:{href:'http://127.0.0.1:1234/',origin:'http://127.0.0.1:1234'},parent:{postMessage:e=>events.push(e)},addEventListener:(k,f)=>handlers.set(k,f),
fetch:async (url, options)=>{if(url==='/api/sdk/runtime-issue'){records.push(JSON.parse(options.body));return {ok:true}}
if(abort){const e=new Error('cancelled');e.name='AbortError';throw e}
return {ok:false,status:500}}}
vm.runInNewContext(source,{window:win,URL,Error,Set,JSON})
await assert.rejects(win.fetch('/api/records?secret=private'),e=>!e.message.includes('500') && e.message.includes('修复'))
assert.equal(events[0].kind,'calabash-tool-issue')
assert.equal(records[0].status,500)
assert(!JSON.stringify(records).includes('private'))
await assert.rejects(win.fetch('/api/records?secret=other'))
assert.equal(events.length,1)
abort=true
await assert.rejects(win.fetch('/api/other'),e=>e.name==='AbortError')
assert.equal(events.length,1)
console.log('Runtime failures reject with friendly text, notify host, and retain no query/body data')
