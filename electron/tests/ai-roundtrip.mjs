/** Full host consent → DSH mock → private stdio → actual worker → result file. */
import assert from 'node:assert/strict'
import { mkdtemp,rm,readFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve,join } from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
const root=resolve(import.meta.dirname,'../..')
const installed=process.env.CALABASH_INSTALLED_APP
const resources=installed&&join(installed,process.platform==='win32'?'resources':'Contents/Resources')
const upstream=join(root,'build/harness',JSON.parse(await readFile(join(root,'electron/harness.lock.json'),'utf8')).commit)
const packages=resources?join(resources,'app/dsh'):upstream
const load=relative=>import(pathToFileURL(join(upstream,relative)).href)
const installedRequire=resources&&createRequire(join(packages,'package.json'))
const dependency=async(name,path)=>resources?import(pathToFileURL(installedRequire.resolve(name)).href):load(path)
const home=await mkdtemp(join(tmpdir(),'calabash-ai-roundtrip-'))
const keys=['HOME','USERPROFILE','CALABASH_REPOSITORY','CALABASH_PYTHON','CALABASH_PACKAGED_BACKEND','CALABASH_FRONTEND_RUNTIME']
const previous=Object.fromEntries(keys.map(key=>[key,process.env[key]]))
Object.assign(process.env,{HOME:home,USERPROFILE:home,CALABASH_REPOSITORY:resources?home:root,CALABASH_PYTHON:resources?join(resources,'calabash/backend',process.platform==='win32'?'calabash-backend.exe':'calabash-backend'):join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python')})
if(resources)Object.assign(process.env,{CALABASH_PACKAGED_BACKEND:'1',CALABASH_FRONTEND_RUNTIME:join(resources,'calabash/frontend-runtime')})
let ctx
try{
  const {Context}=await dependency('@deepseek-ai/cordis','vendor/cordis/lib/index.js')
  const {default:Llm,LlmAdapter}=await dependency('@deepseek-ai/dsh-llm','packages/llm/llm/lib/index.js')
  const {default:Projections}=await dependency('@deepseek-ai/dsh-session-projection','packages/session/session-projection/lib/index.js')
  const {default:SystemPrompt}=await dependency('@deepseek-ai/dsh-system-prompt','packages/core/system-prompt/lib/index.js')
  const {default:Tools}=await dependency('@deepseek-ai/dsh-tools','packages/core/tools/lib/index.js')
  const {default:Workspace}=await dependency('@calabash/harness-workspace','packages/client/calabash-workspace/lib/index.js')
  ctx=new Context();await ctx.plugin(SystemPrompt);await ctx.plugin(Tools);await ctx.plugin(Projections);await ctx.plugin(Llm)
  let requests=[],answer='Synthetic summary'
  class Model extends LlmAdapter{
    async resolveModel(provider,id){return{provider,id,name:id}}
    async listModels(provider){return[{provider,id:'synthetic',name:'Synthetic model'}]}
    async *stream(options){requests.push(options);yield{type:'text-delta',index:0,text:answer};yield{type:'finish',reason:{kind:'stop'}}}
  }
  const registration=ctx.llm.registerAdapter(['synthetic-only'],new Model())
  await ctx.plugin(Workspace)
  const workspace=ctx.calabashWorkspace
  const files={
    'tool.json':JSON.stringify({format:'calabash-react-tool',version:1,project:'demo',name:'ai_acceptance',title:'AI acceptance'}),
    'backend/main.py':'def setup(app, sdk):\n    pass\n',
    'frontend/App.tsx':"import {officeActions,CalabashJobStatus,CalabashResults} from '@calabash/ui'; export default function App(){return <main><button onClick={()=>void officeActions.start('ai.text',{task:'summarize',text:'Synthetic'})}>Summarize</button><CalabashJobStatus/><CalabashResults/></main>}",
  }
  const buildAbort=new AbortController(), notices=[]
  let resolveReady
  const readyNotice=new Promise(resolve=>{resolveReady=resolve})
  const observing=(async()=>{for await(const raw of workspace.watchPreview('synthetic-session',buildAbort.signal)){const value=JSON.parse(raw);notices.push(value);if(value.preview_revision)resolveReady(value)}})()
  let sequence=0
  for(const[path,content]of Object.entries(files))await workspace.agent('write_tool_file',{project:'demo',name:'ai_acceptance',path,content},'synthetic-session','write-'+sequence++)
  assert.equal(notices.some(value=>value.preview_revision),false,'writes alone must not open a preview')
  const checked=JSON.parse(await workspace.agent('check_tool_build',{project:'demo',name:'ai_acceptance'},'synthetic-session','check-ready'))
  let readinessTimer
  const event=await Promise.race([readyNotice,new Promise((_,reject)=>{readinessTimer=setTimeout(()=>reject(Error('Build event missing')),10000)})]).finally(()=>clearTimeout(readinessTimer))
  assert.equal(event.preview_revision,checked.revision,'only the completed current revision is announced')
  buildAbort.abort();await observing
  const preview=JSON.parse(await workspace.preview('synthetic-session',false))
  const url=new URL(preview.url),token=url.searchParams.get('session')
  const origin=url.origin
  // A passing production build is insufficient: every host UI module must also
  // pass the verified static preview HTTP boundary. Previously runtime-ai-result.ts was 404.
  const htmlResponse=await fetch(origin+'/',{headers:{Authorization:'Bearer '+token}})
  const html=await htmlResponse.text()
  const modules=[...html.matchAll(/src="(\/assets\/[^"?]+\.js)"/g)].map(value=>value[1])
  assert.ok(modules.length,'Preview must serve the verified static build')
  for(const path of ['/api/sdk/runtime-guard.js',...modules]){
    const response=await fetch(origin+path,{headers:{Authorization:'Bearer '+token}})
    assert.equal(response.status,200,path)
    assert.ok(response.headers.get('content-type')?.includes('javascript'),path)
    assert.ok((await response.text()).length>0,path)
  }
  const request=async(path,body)=>{
    const response=await fetch(origin+'/api/sdk'+path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})})
    assert.ok(response.ok,`SDK request failed: ${path}`);return response.json()
  }
  const wait=async(f)=>{const deadline=Date.now()+10000;while(true){const value=await f();if(value)return value;if(Date.now()>deadline)throw Error('Synthetic AI timeout');await new Promise(r=>setTimeout(r,20))}}
  const initial=JSON.parse(await workspace.verification('synthetic-session'))
  assert.equal(initial.state,'pending');assert.equal(initial.business_verified,false)
  const pageReady=await fetch(origin+'/api/sdk/page-evidence',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({code:'PAGE_READY',message:'PRIVATE-PAGE-CONTENT'})})
  assert.ok(pageReady.ok)
  const evidence=JSON.parse(await workspace.agent('read_preview_diagnostics',{project:'demo',name:'ai_acceptance'},'synthetic-session','read-evidence'))
  assert.equal(evidence.state,'partial');assert.equal(evidence.page,'ready');assert.equal(evidence.business_verified,false)
  assert.ok(!JSON.stringify(evidence).includes('PRIVATE-PAGE-CONTENT'))
  for(const path of ['/tool.json','/backend/main.py','/office-action-client.ts','/data.sqlite']) {
    assert.equal((await fetch(origin+path,{headers:{Authorization:'Bearer '+token}})).status,404,path)
  }
  const models=JSON.parse(await workspace.aiModels());assert.equal(models.length,1)
  for(const[task,extra,result]of[
    ['summarize',{},'Synthetic summary'],['translate',{language:'English'},'Translated'],['generate',{},'Generated'],
    ['classify',{labels:['A','B']},'{"label":"A"}'],['extract',{fields:{name:'string',count:'number'}},'{"name":"Synthetic","count":2}'],
  ]){
    answer=result
    await request('/actions/ai.text',{parameters:{task,text:'PRIVATE-SYNTHETIC-CONTENT',...extra}})
    const pending=await wait(async()=>JSON.parse(await workspace.aiPending())[0])
    assert.equal(pending.task,task)
    const before=requests.length
    const review=JSON.parse(await workspace.aiReview(pending.worker_id,pending.request_id,models[0].key))
    assert.equal(requests.length,before)
    assert.equal(review.text,'PRIVATE-SYNTHETIC-CONTENT')
    await workspace.aiApprove(review.id)
    await assert.rejects(()=>workspace.aiApprove(review.id))
    const completed=await wait(async()=>!(await request('/status')).running)
    assert.ok(completed)
    const run=(await request('/action-runs'))[0];assert.equal(run.status,'succeeded',JSON.stringify(run))
    const response=await fetch(origin+'/api/sdk/results/'+run.result.outputs[0].id,{headers:{Authorization:'Bearer '+token}})
    const content=await response.text()
    if(task==='classify'||task==='extract')assert.deepEqual(JSON.parse(content),JSON.parse(result));else assert.equal(content,result)
    assert.equal(requests.length,before+1)
    assert.deepEqual(requests.at(-1).tools,[])
    assert.deepEqual(requests.at(-1).messages,[{role:'user',content:[{type:'text',text:'PRIVATE-SYNTHETIC-CONTENT'}]}])
  }
  await request('/actions/ai.text',{parameters:{task:'summarize',text:'Must not send'}})
  const pending=await wait(async()=>JSON.parse(await workspace.aiPending())[0])
  const count=requests.length
  await workspace.aiReject(pending.worker_id,pending.request_id)
  await wait(async()=>!(await request('/status')).running)
  assert.equal(requests.length,count)
  assert.equal((await request('/action-runs'))[0].error.code,'ai_declined')
  assert.equal((await fetch(origin+'/api/sdk/ai/requests',{headers:{Authorization:'Bearer '+token}})).status,403)
  await request('/actions/ai.text',{parameters:{task:'summarize',text:'Stale model request'}})
  let stale=await wait(async()=>JSON.parse(await workspace.aiPending())[0])
  let view=JSON.parse(await workspace.aiReview(stale.worker_id,stale.request_id,JSON.parse(await workspace.aiModels())[0].key))
  registration.replace(['synthetic-only'])
  await assert.rejects(()=>workspace.aiApprove(view.id))
  assert.equal(requests.length,count)
  await workspace.aiReject(stale.worker_id,stale.request_id)
  await wait(async()=>!(await request('/status')).running)
  await request('/actions/ai.text',{parameters:{task:'summarize',text:'Stale source request'}})
  stale=await wait(async()=>JSON.parse(await workspace.aiPending())[0])
  view=JSON.parse(await workspace.aiReview(stale.worker_id,stale.request_id,JSON.parse(await workspace.aiModels())[0].key))
  await workspace.agent('read_tool_file',{project:'demo',name:'ai_acceptance',path:'frontend/App.tsx'},'synthetic-session','read-stale')
  await workspace.agent('patch_tool_file',{project:'demo',name:'ai_acceptance',path:'frontend/App.tsx',old:'Summarize</button>',new:'Summarize safely</button>'},'synthetic-session','patch-stale')
  await assert.rejects(()=>workspace.aiApprove(view.id))
  await wait(async()=>!(await request('/status')).running)
  assert.equal(requests.length,count)

  assert.equal(JSON.parse(await workspace.verification('synthetic-session')).state,'stale')
  console.log(`PASS ${installed?'installed':'source'}: five AI actions through actual host consent, DSH synthetic adapter, private executor, real worker and result downloads; no provider quota`)
}finally{
  await ctx?.fiber.dispose()
  for(const[key,value]of Object.entries(previous)){if(value===undefined)delete process.env[key];else process.env[key]=value}
  await rm(home,{recursive:true,force:true})
}
