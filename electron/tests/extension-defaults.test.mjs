/** Exercise DSH's real composer: explicit user configuration wins over app defaults. */
import assert from 'node:assert/strict'
import {readFile, mkdtemp, rm} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {tmpdir} from 'node:os'
import {pathToFileURL} from 'node:url'
const root=resolve(import.meta.dirname,'../..')
const lock=JSON.parse(await readFile(join(root,'electron/harness.lock.json'),'utf8'))
const upstream=process.env.CALABASH_HARNESS_SOURCE || join(root,'build/harness',lock.commit)
const load=path=>import(pathToFileURL(join(upstream,path)).href)
const {readProfilePatches}=await load('packages/boot/app-boot/lib/types/profile-context.js')
const {composeEntries}=await load('packages/boot/app-boot/lib/types/profile.js')
const home=await mkdtemp(join(tmpdir(),'calabash-extension-defaults-'))
const previous=process.env.CALABASH_LOCAL_WORKSPACE
try {
  process.env.CALABASH_LOCAL_WORKSPACE='1'
  const ids=['tool-web','tool-skill','mcp-manager','ui-plugin-manager']
  const defaults=[{insert:ids.map(id=>({id,name:'test-'+id,disabled:false}))},...ids.map(id=>({id,disabled:id!=='ui-plugin-manager'}))]
  const context={home,dir:home,patchPath:join(home,'missing.yml'),installAnchor:join(home,'package.json'),overlays:defaults}
  const profile={layers:[],patches:[]}
  let rows=composeEntries([readProfilePatches('test',context,profile)])
  assert.equal(rows.find(row=>row.id==='ui-plugin-manager').disabled,false)
  for(const id of ids.slice(0,3)) assert.equal(rows.find(row=>row.id===id).disabled,true)
  profile.patches=ids.slice(0,3).map(id=>({id,disabled:false}))
  rows=composeEntries([readProfilePatches('test',context,profile)])
  for(const id of ids.slice(0,3)) assert.equal(rows.find(row=>row.id===id).disabled,false)
  profile.patches=[{id:'ui-plugin-manager',disabled:true}]
  rows=composeEntries([readProfilePatches('test',context,profile)])
  assert.equal(rows.find(row=>row.id==='ui-plugin-manager').disabled,true)
  console.log('DSH extension defaults and explicit user override passed')
} finally {
  if(previous===undefined) delete process.env.CALABASH_LOCAL_WORKSPACE
  else process.env.CALABASH_LOCAL_WORKSPACE=previous
  await rm(home,{recursive:true,force:true})
}
