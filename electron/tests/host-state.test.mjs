import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
const root = resolve(import.meta.dirname, '../..')
const upstream = process.env.CALABASH_HARNESS_SOURCE || join(root, 'build/harness', JSON.parse(readFileSync(join(root,'electron/harness.lock.json'))).commit)
const load = name => import(pathToFileURL(join(upstream, 'packages/client/calabash-workspace/lib/types', name)).href)
const { HostTasks } = await load('tasks.js')
const { WorkspaceState } = await load('workspace-state.js')
const home = mkdtempSync(join(tmpdir(),'calabash-host-state-'))
const tick = () => new Promise(resolve => setTimeout(resolve,0))
try {
  const tasks = new HostTasks(join(home,'journal'),2)
  let finishA, finishC, started = []
  const first = tasks.submit('build', { privateSource:'SECRET' }, 'tool:a', 'first', () => { started.push('a'); return new Promise(resolve => {finishA=resolve}) })
  const queued = tasks.submit('publish', {}, 'tool:a', 'second', async () => {started.push('b'); return 'saved'})
  const parallel = tasks.submit('build', {}, 'tool:c', 'third', () => {started.push('c'); return new Promise(resolve => {finishC=resolve})})
  assert.deepEqual(started,['a','c']); assert.equal(tasks.inspect(queued).state,'queued')
  assert.equal(tasks.submit('build',{privateSource:'SECRET'},'tool:a','first',async()=>{throw Error('replay')}),first)
  assert.throws(()=>tasks.submit('build',{changed:true},'tool:a','first',async()=>{}))
  assert.equal(readFileSync(join(home,'journal/tasks.json'),'utf8').includes('SECRET'),false)
  const restored = new HostTasks(join(home,'journal'))
  assert.equal(restored.inspect(first).state,'interrupted')
  finishA({late:'result'}); await tasks.wait(first); await tick(); assert.deepEqual(started,['a','c','b'])
  finishC('other'); await tasks.wait(parallel); await tasks.wait(queued); await tick()
  assert.deepEqual(tasks.inspect(first).result,{late:'result'})
  await tasks.drain(); assert.throws(()=>tasks.submit('build',{},'tool:d','after-exit',async()=>{}))
  const state = new WorkspaceState(join(home,'workspace'))
  state.write({tabs:[{project:'demo',name:'counter',url:'SECRET'}],active:'demo/counter',collapsed:true,query:'hello'})
  const view = new WorkspaceState(join(home,'workspace')).read()
  assert.deepEqual(view,{tabs:[{project:'demo',name:'counter'}],active:'demo/counter',collapsed:true,query:'hello'})
  assert.equal(readFileSync(join(home,'workspace/workspace.json'),'utf8').includes('SECRET'),false)
  assert.throws(()=>state.write({tabs:[{project:'../x',name:'x'}],active:'',collapsed:false,query:''}))
  if (process.platform !== 'win32') {
  const { ProcessSupervisor } = await load('process-supervisor.js')
  const marker = join(home,'file-finished')
  const workerCode = `const http=require('node:http'),fs=require('node:fs');let calls=0;http.createServer((req,res)=>{calls++;if(calls===2)fs.writeFileSync(process.argv[1],'done');res.setHeader('Content-Type','application/json');res.end(JSON.stringify({running:calls<2}));}).listen(0,'127.0.0.1',function(){console.log(this.address().port)})`
  const child = spawn(process.execPath,['-e',workerCode,marker],{detached:process.platform!=='win32',stdio:['ignore','pipe','pipe']})
  const port = await new Promise(resolve => child.stdout.once('data',data=>resolve(Number(String(data).trim()))))
  const exited = new Promise(resolve => child.once('exit',resolve))
  const supervisor = new ProcessSupervisor()
  supervisor.receive({kind:'start',pid:child.pid,group:process.platform!=='win32',role:'tool'})
  supervisor.receive({kind:'control',pid:child.pid,control:{port,token:'synthetic',hostToken:'synthetic'}})
  supervisor.receive({kind:'ready',pid:child.pid})
  await supervisor.drain(); await exited
  assert.equal(readFileSync(marker,'utf8'),'done','Host waits for current file before terminating a business worker')
  assert.equal(supervisor.busy,false)
  console.log('PASS: TypeScript process supervisor waits for safe-file completion before reclaiming an orphan worker')
  }
  console.log('PASS: per-tool serialization, bounded parallel tasks, late-result requery, no replay, payload-free journals and inert workspace recovery')
} finally {rmSync(home,{recursive:true,force:true})}
