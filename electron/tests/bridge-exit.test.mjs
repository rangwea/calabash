/** Real host crash simulation: pipe EOF drains a detached Python executor and its tool. */
import assert from 'node:assert/strict'
import { spawn, execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
const root = resolve(import.meta.dirname,'../..')
const upstream = process.env.CALABASH_HARNESS_SOURCE || join(root,'build/harness',JSON.parse(readFileSync(join(root,'electron/harness.lock.json'))).commit)
if (process.argv.includes('--driver')) {
  const { PythonBridge } = await import(pathToFileURL(join(upstream,'packages/client/calabash-workspace/lib/types/bridge.js')).href)
  const bridge = new PythonBridge()
  const tool = await bridge.call('tools.open',{project:'demo',name:'counter'})
  console.log(JSON.stringify(tool))
  process.stdin.resume()
  process.stdin.once('end',()=>{void bridge.stop()})
} else {
  const home = mkdtempSync(join(tmpdir(),'calabash-bridge-exit-'))
  const env = {...process.env,HOME:home,CALABASH_REPOSITORY:root,CALABASH_PYTHON:join(root,'.venv',process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')}
  let child
  try {
    execFileSync(env.CALABASH_PYTHON,['-c',"import asyncio; from tests.test_tool_bundles import fixture; from service.tools.tool_workers import build_bundle; from service.tools import tool_bundles as b; f=fixture(); built=asyncio.run(build_bundle(f)); b.write('demo','counter',f,built_dist=built/'dist')"],{cwd:root,env,stdio:'pipe'})
    child = spawn(process.execPath,[import.meta.filename,'--driver'],{cwd:root,env,stdio:['pipe','pipe','pipe']})
    const tool = await new Promise((resolve,reject)=>{let buffer='';child.stdout.on('data',chunk=>{buffer+=chunk;if(buffer.includes('\n'))resolve(JSON.parse(buffer.split('\n')[0]))});child.once('exit',()=>reject(Error('Driver exited before tool startup')))})
    const origin = new URL(tool.url).origin
    assert.equal((await fetch(origin+'/health')).status,200)
    const exit = new Promise(resolve=>child.once('exit',resolve))
    child.kill('SIGINT'); await exit
    let reclaimed=false
    for(let i=0;i<60;i++){
      try{await fetch(origin+'/health',{signal:AbortSignal.timeout(300)})}catch{reclaimed=true;break}
      await new Promise(resolve=>setTimeout(resolve,200))
    }
    assert.equal(reclaimed,true,'Host SIGINT must not orphan the Python tool listener')
    console.log('PASS: real Host SIGINT → detached executor pipe EOF → safe worker shutdown → listener reclaimed')
  } finally { if(child?.exitCode===null&&child.signalCode===null)child.stdin.end(); rmSync(home,{recursive:true,force:true}) }
}
