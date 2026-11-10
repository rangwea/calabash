/** Real DSH adapter with synthetic output; no credentials, providers or user files. */
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { resolve,join } from 'node:path'
import { pathToFileURL } from 'node:url'
const root=resolve(import.meta.dirname,'../..')
const upstream=process.env.CALABASH_HARNESS_SOURCE||join(root,'build/harness',JSON.parse(await readFile(join(root,'electron/harness.lock.json'),'utf8')).commit)
const load=path=>import(pathToFileURL(join(upstream,path)).href)
const {Context}=await load('vendor/cordis/lib/index.js')
const {default:Llm,LlmAdapter}=await load('packages/llm/llm/lib/index.js')
const {AIActionHost}=await load('packages/client/calabash-workspace/lib/types/ai-actions.js')
const ctx=new Context()
await ctx.plugin(Llm)
let mode='success',requests=[],metadata=[]
class Model extends LlmAdapter {
  async resolveModel(provider,id){if(mode==='prepare-error')throw Error('PRIVATE-CONNECTION-ERROR');return{provider,id,name:id}}
  async listModels(provider){return[{provider,id:'synthetic',name:'Synthetic local model'}]}
  async *stream(options){
    requests.push(options)
    if(mode==='hang'){await new Promise(()=>{});return}
    if(mode==='tool'){yield{type:'tool-call-delta',index:0,id:'denied',name:'shell',argumentsDelta:'{}'};return}
    yield{type:'text-delta',index:0,text:mode==='large'?'x'.repeat(33000):'Synthetic result'}
    yield{type:'finish',reason:{kind:mode==='truncated'?'max-tokens':mode==='error'?'error':'stop'}}
  }
}
ctx.llm.registerAdapter(['synthetic-only'],new Model())
const payload={task:'summarize',text:'PRIVATE-SYNTHETIC-TEXT📄',language:'',labels:[],fields:{},output_name:'ai-result'}
const meta={worker_id:'a'.repeat(32),request_id:'b'.repeat(32),invocation_id:'c'.repeat(32),revision:'d'.repeat(64),digest:'e'.repeat(64),expires:Date.now()/1000+600,task:'summarize',title:'总结内容',characters:Array.from(payload.text).length,state:'pending',project:'demo',name:'synthetic'}
let state='pending',stale=false,delivered=[],calls=[]
const bridge={started:true,async call(method,input){
  calls.push([method,input.operation])
  if(method==='ai.pending')return state==='pending'?[{...meta}]:[]
  if(stale)throw Error('Synthetic source changed')
  if(input.request_id!==meta.request_id||input.worker_id!==meta.worker_id||input.digest!==meta.digest)throw Error('Binding mismatch')
  switch(input.operation){
    case'review':return{...meta,payload}
    case'begin':if(state!=='pending')throw Error('Already consumed');state='running';return{lease:'f'.repeat(32)}
    case'check':if(state!=='running')throw Error('Cancelled');return{ok:true}
    case'deliver':assert.equal(state,'running');delivered.push(input.text);state='done';return{ok:true}
    case'reject':case'fail':state='done';return{ok:true}
    default:throw Error('Unknown control')
  }
}}
let now=Date.now()
const host=new AIActionHost(bridge,()=>ctx.llm,()=>now,event=>metadata.push(event))
const reset=()=>{state='pending';stale=false;mode='success';meta.expires=now/1000+600;delivered=[]}
const review=async()=>host.review(meta.worker_id,meta.request_id,(await host.models())[0].key)
try{
  await assert.rejects(()=>host.approve('invented'))
  assert.equal(requests.length,0)
  let view=await review()
  assert.equal(requests.length,0,'Review must never dispatch a provider call')
  await Promise.all([host.approve(view.id),assert.rejects(()=>host.approve(view.id))])
  assert.equal(requests.length,1);assert.deepEqual(delivered,['Synthetic result'])
  assert.deepEqual(requests[0].messages,[{role:'user',content:[{type:'text',text:payload.text}]}])
  assert.deepEqual(requests[0].tools,[]);assert.equal(requests[0].sessionId,undefined)
  assert.equal(requests[0].maxTokens,2048)
  assert.ok(!JSON.stringify(metadata).includes(payload.text))
  reset();view=await review();await host.reject(meta.worker_id,meta.request_id);await assert.rejects(()=>host.approve(view.id));assert.equal(requests.length,1)
  reset();view=await review();now+=601000;await assert.rejects(()=>host.approve(view.id));assert.equal(requests.length,1)
  reset();view=await review();host.invalidate();await assert.rejects(()=>host.approve(view.id));assert.equal(requests.length,1)
  reset();view=await review();stale=true;await assert.rejects(()=>host.approve(view.id));assert.equal(requests.length,1)
  for(const failure of ['truncated','tool','large','error']){
    reset();view=await review();mode=failure
    const before=requests.length
    await assert.rejects(()=>host.approve(view.id))
    assert.equal(requests.length,before+1,'Failed model calls must never retry automatically')
    assert.deepEqual(delivered,[])
  }
  reset();mode='prepare-error';await assert.rejects(()=>review(),error=>!String(error).includes('PRIVATE-CONNECTION-ERROR'));
  reset();view=await review();mode='hang'
  const running=host.approve(view.id)
  await new Promise(resolve=>setTimeout(resolve,10));host.cancel(view.id)
  await assert.rejects(()=>running);assert.deepEqual(delivered,[])
  console.log('PASS: real DSH prepared model call; per-request consent, no implicit context/tools, no retries, cancellation, expiry, source/model isolation, metadata-only records')
}finally{await host.stop();await ctx.fiber.dispose()}
