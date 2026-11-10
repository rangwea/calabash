import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
const source=readFileSync(new URL('../scripts/tool_runtime_guard.js',import.meta.url),'utf8')
const evidence=[],listeners=new Map();let inspect,timer;const root={children:[],textContent:'',getClientRects:()=>[{}]}
const win={location:{origin:'http://127.0.0.1:1234',href:'http://127.0.0.1:1234/'},parent:{postMessage(){}},addEventListener:(key,handler)=>listeners.set(key,handler),fetch:async(path,options)=>{assert.ok(['/api/sdk/page-evidence','/api/sdk/runtime-issue'].includes(path),'No business endpoint may be called by verification');if(path==='/api/sdk/page-evidence')evidence.push(JSON.parse(options.body));return{ok:true}}}
class Observer{constructor(callback){inspect=callback}observe(){}disconnect(){}}
vm.runInNewContext(source,{window:win,document:{getElementById:()=>root,documentElement:{}},MutationObserver:Observer,setTimeout:callback=>{timer=callback},clearTimeout(){},URL,Set,Error,JSON,Number})
assert.equal(evidence.length,0)
root.children=[{}];inspect();assert.equal(evidence[0].code,'PAGE_READY')
listeners.get('error')({filename:'http://127.0.0.1:1234/@fs/private/home/frontend/App.tsx?key=PRIVATE',lineno:12,colno:3,message:'SECRET-PROMPT',error:new Error('SECRET-STACK')})
assert.equal(evidence[1].file,'frontend/App.tsx')
assert.equal(evidence[1].line,12)
assert(!JSON.stringify(evidence).includes('PRIVATE'))
assert(!JSON.stringify(evidence).includes('SECRET'))
assert(!JSON.stringify(evidence).includes('private/home'))
console.log('PASS: real mount evidence and safe script location; no page text, input values, stack or business probes')
