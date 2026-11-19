/** Portable Node dependency tree: no junctions or directory symlinks in Windows installers. */
import {cpSync,existsSync,mkdirSync,readFileSync} from 'node:fs'
import {dirname,join,relative,sep} from 'node:path'

export class PackageTree {
  constructor(root, resolvePackage) { this.root=root; this.resolve=resolvePackage; this.locations=new Map(); this.copied=new Map() }
  install(source, parent=this.root, depth=0) {
    if(depth>40) throw new Error('Package dependency nesting exceeds portable layout limit')
    const manifest=JSON.parse(readFileSync(join(source,'package.json'),'utf8'))
    const name=manifest.name
    if(!name || name.split('/').some(part=>!part || part==='..' || part==='.') || name.includes('\\')) throw new Error('Invalid installed package name')
    // Follow Node's nearest-ancestor lookup before choosing a physical location.
    for(let dir=parent;;dir=dirname(dir)) {
      const location=join(dir,'node_modules',name)
      if(this.locations.has(location)) {
        if(this.locations.get(location)===source) return location
        break
      }
      if(dir===this.root) break
      if(!dir.startsWith(this.root+sep)) throw new Error('Package parent escaped install root')
    }
    const top=join(this.root,'node_modules',name)
    const destination=this.locations.has(top)?join(parent,'node_modules',name):top
    if(this.locations.has(destination)) throw new Error('Conflicting package install location')
    this.locations.set(destination,source)
    if(!this.copied.has(source)) this.copied.set(source,destination)
    mkdirSync(dirname(destination),{recursive:true})
    cpSync(source,destination,{recursive:true,dereference:true,filter:path=>!relative(source,path).split(sep).some(part=>['node_modules','.git','.desktop-build'].includes(part))})
    for(const dependency of Object.keys({...manifest.dependencies,...manifest.peerDependencies,...manifest.optionalDependencies})) {
      let resolved
      try { resolved=this.resolve(dependency,source) }
      catch(error) { if(manifest.optionalDependencies?.[dependency] || manifest.peerDependenciesMeta?.[dependency]?.optional) continue; throw error }
      this.install(resolved,destination,depth+1)
    }
    return destination
  }
  shared() {
    return [...this.locations].filter(([path])=>{
      const source=this.locations.get(path)
      const name=JSON.parse(readFileSync(join(source,'package.json'),'utf8')).name
      return path===join(this.root,'node_modules',name) && existsSync(path)
    }).map(([destination,source])=>{
      const {name,version}=JSON.parse(readFileSync(join(source,'package.json'),'utf8'))
      return {source,destination,name,version}
    })
  }
}
