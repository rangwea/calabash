import {test} from 'node:test'
import assert from 'node:assert/strict'
import {mkdtempSync,mkdirSync,writeFileSync,rmSync,lstatSync,readdirSync,readFileSync} from 'node:fs'
import {join} from 'node:path'
import {tmpdir} from 'node:os'
import {createRequire} from 'node:module'
import {PackageTree} from '../scripts/package_tree.mjs'

test('portable package tree resolves cycles and conflicting versions without directory links',()=>{
 const root=mkdtempSync(join(tmpdir(),'calabash-package-tree-'))
 try {
  const sources=join(root,'sources'), output=join(root,'app'), nodes={}
  for(const [id,name,version,dependencies] of [['a','a','1',{b:'1',shared:'1'}],['b','b','1',{a:'1',shared:'2'}],['s1','shared','1',{}],['s2','shared','2',{}]]){
   const path=join(sources,id);mkdirSync(path,{recursive:true});writeFileSync(join(path,'package.json'),JSON.stringify({name,version,main:'index.cjs',dependencies}));writeFileSync(join(path,'index.cjs'),`module.exports=${JSON.stringify(version)}`);nodes[id]=path
  }
  const tree=new PackageTree(output,(name,source)=>name==='shared'?(source===nodes.a?nodes.s1:nodes.s2):nodes[name])
  const a=tree.install(nodes.a),b=tree.install(nodes.b)
  assert.equal(createRequire(join(a,'index.cjs'))('shared'),'1')
  assert.equal(createRequire(join(b,'index.cjs'))('shared'),'2')
  assert.equal(createRequire(join(b,'index.cjs'))('a'),'1')
  const audit=path=>{for(const item of readdirSync(path)){const child=join(path,item),stat=lstatSync(child);assert.equal(stat.isSymbolicLink(),false);if(stat.isDirectory())audit(child)}}
  audit(output)
  assert.equal(JSON.parse(readFileSync(join(a,'package.json'))).name,'a')
 } finally {rmSync(root,{recursive:true,force:true})}
})
