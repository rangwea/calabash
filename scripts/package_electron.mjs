/** Package the pinned, built DSH runtime and Calabash runtimes without source-tree links. */
import {createHash} from 'node:crypto'
import {createRequire} from 'node:module'
import {cpSync,existsSync,readFileSync,writeFileSync,mkdirSync,rmSync,realpathSync,symlinkSync,readdirSync,lstatSync,unlinkSync} from 'node:fs'
import {join,resolve,dirname,relative,basename,sep} from 'node:path'
import {spawnSync} from 'node:child_process'
import {verifyCheckout,overlayFingerprint} from './harness.mjs'
const root=resolve(import.meta.dirname,'..')
const metadata=JSON.parse(readFileSync(join(root,'package.json')))
const lock=JSON.parse(readFileSync(join(root,'electron/harness.lock.json')))
const upstream=resolve(process.env.CALABASH_HARNESS_SOURCE || join(root,'build/harness',lock.commit))
await verifyCheckout(upstream,lock)
const built=JSON.parse(readFileSync(join(upstream,'.calabash-build.json')))
if(built.commit!==lock.commit || built.overlay!==await overlayFingerprint(root)) throw new Error('Rebuild Electron before packaging changed overlays')
// Always prepare official metadata; packaging must not depend on a previous dev launch.
const prepare=spawnSync(process.execPath,[join(upstream,'node_modules/tsx/dist/cli.mjs'),join(upstream,'apps/desktop/scripts/calabash-prepare-project.ts')],{cwd:upstream,env:process.env,stdio:'inherit'})
if(prepare.error) throw prepare.error
if(prepare.status!==0) throw new Error('DSH project preparation failed')
const stage=join(root,'build/electron-package')
const app=join(stage,'app'), dsh=join(app,'dsh')
const output=join(root,'dist/electron')
if(process.platform!=='darwin'||process.arch!=='arm64') throw new Error('This local installer target currently requires macOS arm64')
const backend=join(root,'build/electron-backend/calabash-backend')
const compiler=join(root,'build/frontend-runtime')
for(const file of [join(backend,'calabash-backend'),join(compiler,'node'),join(upstream,'.calabash-build.json')]) {
 if(!existsSync(file)) throw new Error('Missing packaging input: '+file)
}
rmSync(stage,{recursive:true,force:true});mkdirSync(dsh,{recursive:true})
const copied=new Map(),shared=new Map()
function json(path){return JSON.parse(readFileSync(path,'utf8'))}
function resolvePackage(name,from){
 for(let dir=from;;dir=dirname(dir)){
  const candidate=join(dir,'node_modules',name)
  if(existsSync(join(candidate,'package.json'))) return realpathSync(candidate)
  if(dirname(dir)===dir) break
 }
 const candidate=join(upstream,'node_modules/.pnpm/node_modules',name)
 if(existsSync(join(candidate,'package.json'))) return realpathSync(candidate)
 throw new Error('Installed dependency missing: '+name+' from '+from)
}
function linkPackage(source,target){
 const installed=materialize(source);mkdirSync(dirname(target),{recursive:true})
 if(!existsSync(target)) symlinkSync(relative(dirname(target),installed),target,'dir')
}
function materialize(input){
 const source=realpathSync(input)
 if(copied.has(source)) return copied.get(source)
 const manifest=json(join(source,'package.json'))
 const key=createHash('sha256').update(relative(upstream,source)).digest('hex').slice(0,20)
 const destination=join(dsh,'.packages',key)
 copied.set(source,destination)
 cpSync(source,destination,{recursive:true,dereference:true,filter:path=>{
  const parts=relative(source,path).split(sep)
  return !parts.some(p=>['node_modules','.git','.desktop-build'].includes(p))
 }})
 const dependencies={...manifest.dependencies,...manifest.peerDependencies,...manifest.optionalDependencies}
 for(const name of Object.keys(dependencies || {})){
  let dependency
  try{dependency=resolvePackage(name,source)}catch(error){
   if(manifest.optionalDependencies?.[name] || manifest.peerDependenciesMeta?.[name]?.optional) continue
   throw error
  }
  linkPackage(dependency,join(destination,'node_modules',name))
 }
 // Shared packages are projected for external plugins. Keep exact versioned
 // dependency links inside each package; do not flatten incompatible versions.
 if(!shared.has(manifest.name)) shared.set(manifest.name,{source,destination,version:manifest.version})
 return destination
}
for(const path of ['apps/cli','apps/desktop-host','packages/client/calabash-workspace']) materialize(join(upstream,path))
// Register Calabash as an installation-owned dependency so DSH's public
// runtime resolver does not treat it as a third-party profile package.
const cli=materialize(join(upstream,'apps/cli'))
const cliManifest=json(join(cli,'package.json'))
cliManifest.dependencies={...cliManifest.dependencies,'@calabash/harness-workspace':metadata.version}
writeFileSync(join(cli,'package.json'),JSON.stringify(cliManifest))
linkPackage(join(upstream,'packages/client/calabash-workspace'),join(cli,'node_modules/@calabash/harness-workspace'))
const shell=json(join(upstream,'apps/desktop/package.json'))
for(const name of Object.keys(shell.dependencies)) materialize(resolvePackage(name,join(upstream,'apps/desktop')))
for(const [name,entry] of shared){linkPackage(entry.source,join(dsh,'node_modules',name))}
for(const name of Object.keys(shell.dependencies)) linkPackage(resolvePackage(name,join(upstream,'apps/desktop')),join(app,'node_modules',name))
const dev=join(upstream,'apps/desktop/.desktop-build/development/project')
const descriptor=json(join(dev,'desktop-runtime.json'))
descriptor.sharedPackages=[...shared].map(([name,v])=>({name,version:v.version,path:'node_modules/'+name})).sort((a,b)=>a.name.localeCompare(b.name))
// File and link integrity is recorded below for this independently materialized tree.
descriptor.files=[]
writeFileSync(join(dsh,'desktop-runtime.json'),JSON.stringify(descriptor))
writeFileSync(join(dsh,'package.json'),JSON.stringify(json(join(dev,'package.json'))))
cpSync(join(upstream,'calabash.patch.yml'),join(dsh,'calabash.patch.yml'))
cpSync(join(upstream,'apps/desktop/lib'),join(app,'lib'),{recursive:true})
cpSync(join(upstream,'apps/desktop/renderer'),join(app,'renderer'),{recursive:true})
writeFileSync(join(app,'package.json'),JSON.stringify({name:'calabash',productName:'Calabash',version:metadata.version,main:'lib/main.js',type:'module',private:true,license:metadata.license,author:'wikia',dependencies:shell.dependencies}))
const runtime=join(stage,'runtime')
cpSync(join(upstream,'apps/desktop/.desktop-build/targets/mac-arm64/runtime'),runtime,{recursive:true,dereference:true})
cpSync(join(upstream,'apps/desktop/scripts/node-bin'),join(runtime,'bin'),{recursive:true})
const calabash=join(stage,'calabash')
cpSync(backend,join(calabash,'backend'),{recursive:true,dereference:true})
cpSync(compiler,join(calabash,'frontend-runtime'),{recursive:true,dereference:true})
for(const name of ['LICENSE','NOTICE']) cpSync(join(root,name),join(calabash,name))
cpSync(join(root,'electron/DSH-LICENSE.txt'),join(calabash,'DSH-LICENSE.txt'))
// Refuse links back into the checkout or external user data before packaging.
const relocations=[...copied.entries(),[backend,join(calabash,'backend')],[compiler,join(calabash,'frontend-runtime')],
 [join(upstream,'apps/desktop/.desktop-build/targets/mac-arm64/runtime'),runtime]].sort((a,b)=>b[0].length-a[0].length)
function audit(directory,base=stage){for(const entry of readdirSync(directory)){
 const path=join(directory,entry),info=lstatSync(path)
 if(info.isSymbolicLink()) {
  const real=realpathSync(path)
  if(!real.startsWith(base+sep)) {
   if(base!==stage) throw new Error('External installed runtime link: '+path)
   const mapping=relocations.find(([source])=>real===source || real.startsWith(source+sep))
   if(!mapping) throw new Error('External runtime link: '+path)
   const target=join(mapping[1],relative(mapping[0],real))
   if(!existsSync(target)) throw new Error('Relocated link target missing: '+path)
   unlinkSync(path);symlinkSync(relative(dirname(path),target),path)
  }
 }
 else if(info.isDirectory()) audit(path,base)
}}
audit(stage)
writeFileSync(join(calabash,'provenance.json'),JSON.stringify({app:metadata.version,dsh:lock.commit,packages:copied.size,platform:process.platform,arch:process.arch}))
const require=createRequire(join(upstream,'apps/desktop/package.json'))
const builder=require.resolve('electron-builder/out/cli/cli.js')
const electron=dirname(dirname(require.resolve('electron/package.json')))
const config={appId:'com.wikia.calabash',productName:'Calabash',asar:false,npmRebuild:false,
 directories:{app,output},electronDist:join(electron,'electron/dist'),electronVersion:json(require.resolve('electron/package.json')).version,
 files:['**/*','!dsh/**'],extraResources:[{from:runtime,to:'runtime'},{from:calabash,to:'calabash'},{from:join(root,'electron/icons/icon.png'),to:'icon.png'}],
 mac:{icon:join(root,'electron/icons/icon.icns'),identity:null,category:'public.app-category.productivity'},publish:null}
const configPath=join(stage,'builder.mjs')
writeFileSync(configPath,`import {cpSync,constants} from 'node:fs';import {join} from 'node:path';\nexport default {...${JSON.stringify(config)},afterPack(context){cpSync(${JSON.stringify(dsh)},join(context.appOutDir,'Calabash.app/Contents/Resources/app/dsh'),{recursive:true,verbatimSymlinks:true,mode:constants.COPYFILE_FICLONE});}}`)
const result=spawnSync(process.execPath,[builder,'--config',configPath,'--mac','--arm64','--dir','--publish','never'],{cwd:root,stdio:'inherit',env:{...process.env,CSC_IDENTITY_AUTO_DISCOVERY:'false'}})
if(result.status!==0) throw new Error('Electron packaging failed')
const packaged=join(output,'mac-arm64/Calabash.app')
audit(packaged,packaged)
const applications=join(output,'mac-arm64/Applications')
if(!existsSync(applications)) symlinkSync('/Applications',applications)
const dmg=join(output,`Calabash-${metadata.version}-macos-arm64.dmg`)
const image=spawnSync('hdiutil',['create','-volname','Calabash','-srcfolder',join(output,'mac-arm64'),'-ov','-format','UDZO',dmg],{stdio:'inherit'})
if(image.status!==0) throw new Error('DMG creation failed')
console.log('Packaged '+dmg+' ('+copied.size+' packages)')
